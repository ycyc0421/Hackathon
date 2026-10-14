"""验证发布与回退不会覆盖运行配置、任务数据或旧版本依赖。"""

from io import BytesIO
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import backend


class ModelReadinessTests(unittest.TestCase):
    def setUp(self):
        self.elapsed = 0
        clock = patch("backend.time.monotonic", side_effect=lambda: self.elapsed)
        sleep = patch("backend.time.sleep", side_effect=self.advance)
        clock.start()
        sleep.start()
        self.addCleanup(clock.stop)
        self.addCleanup(sleep.stop)
        self.worker = {"status": "ok", "pipeline_version": "v1.6",
                       "rec_backend": "llama-cpp-server", "busy": False}

    def advance(self, seconds):
        self.elapsed += seconds

    @patch("backend.urlopen")
    def test_ready_worker_waits_for_recognition_model_loading(self, urlopen):
        attempts = []
        def respond(url, **kwargs):
            if url == "http://127.0.0.1:18082/health":
                return BytesIO(json.dumps(self.worker).encode())
            self.assertEqual(url, "http://127.0.0.1:18083/health")
            attempts.append(self.elapsed)
            if len(attempts) == 1:
                raise HTTPError(url, 503, "Loading model", {}, None)
            return BytesIO(b'{"status":"ok"}')
        urlopen.side_effect = respond
        backend.wait_model_healthy()
        self.assertEqual(attempts, [0, 1])

    @patch("backend.urlopen")
    def test_unavailable_recognition_model_times_out(self, urlopen):
        for unavailable in (URLError("connection refused"),
                            HTTPError("http://127.0.0.1:18083/health", 503, "Loading model", {}, None),
                            b'{"status":"loading"}'):
            with self.subTest(unavailable=unavailable):
                self.elapsed = 0
                def respond(url, **kwargs):
                    if url == "http://127.0.0.1:18082/health":
                        return BytesIO(json.dumps(self.worker).encode())
                    self.assertEqual(url, "http://127.0.0.1:18083/health")
                    if isinstance(unavailable, Exception):
                        raise unavailable
                    return BytesIO(unavailable)
                urlopen.side_effect = respond
                with self.assertRaisesRegex(RuntimeError, "120 秒"):
                    backend.wait_model_healthy()
                self.assertEqual(self.elapsed, 120)

    @patch("backend.urlopen")
    def test_ready_recognition_model_does_not_override_worker_checks(self, urlopen):
        for invalid in ({"pipeline_version": "v1.5"}, {"rec_backend": "native"},
                        {"busy": True}, {"status": "starting"}):
            with self.subTest(invalid=invalid):
                self.elapsed = 0
                def respond(url, **kwargs):
                    payload = {**self.worker, **invalid} if "18082" in url else {"status": "ok"}
                    return BytesIO(json.dumps(payload).encode())
                urlopen.side_effect = respond
                with self.assertRaisesRegex(RuntimeError, "120 秒"):
                    backend.wait_model_healthy()


class EnvironmentReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'app'
        self.root.mkdir()
        self.identity = 'python312-cpu'
        self.releases = []
        runner = patch('backend.run', side_effect=self.command)
        self.run = runner.start()
        self.addCleanup(runner.stop)

    def command(self, *args, **kwargs):
        if 'venv' in args:
            binary = Path(args[-1]) / 'bin/python'
            binary.parent.mkdir()
            binary.touch()
        if 'freeze' in args:
            kwargs['stdout'].write('fastapi==0.115.0\n')
        return subprocess.CompletedProcess(args, 0, stdout=self.identity)

    def release(self):
        release = self.root / 'releases' / str(len(self.releases))
        (release / 'backend').mkdir(parents=True)
        (release / 'backend/requirements.txt').write_text('fastapi==0.115.0\n')
        (release / 'backend/requirements-ocr.txt').write_text('-r requirements.txt\npaddleocr==3.7.0\n')
        self.releases.append(release)
        return release

    def prepare(self, release, ocr=True):
        return backend.prepare_environment(self.root, release, '/opt/python312', ocr)

    def test_same_inputs_reuse_completed_environment_without_installing(self):
        first = self.release()
        self.prepare(first)
        environment = (first / '.venv').resolve()
        lock = (environment / 'requirements.lock').read_bytes()
        self.run.reset_mock()
        second = self.release()
        python = self.prepare(second)
        self.assertEqual((second / '.venv').resolve(), environment)
        self.assertEqual(python, str(second / '.venv/bin/python'))
        self.assertFalse(any('install' in call.args or 'venv' in call.args or 'freeze' in call.args
                             for call in self.run.call_args_list))
        self.assertTrue(any('check' in call.args for call in self.run.call_args_list))
        self.assertEqual((first / 'requirements.lock').read_bytes(), lock)
        self.assertEqual((second / 'requirements.lock').read_bytes(), lock)
        self.assertEqual((environment / 'requirements.lock').read_bytes(), lock)

    def test_dependency_python_and_ocr_changes_get_separate_environments(self):
        first = self.release()
        self.prepare(first)
        original = (first / '.venv').resolve()
        for change in ('base', 'ocr', 'python', 'disabled', 'paddle'):
            with self.subTest(change=change):
                release = self.release()
                if change in ('base', 'ocr'):
                    name = 'requirements.txt' if change == 'base' else 'requirements-ocr.txt'
                    path = release / 'backend' / name
                    path.write_text(path.read_text() + 'Pillow==11.0.0\n')
                self.identity = 'python312-new' if change == 'python' else 'python312-cpu'
                with patch('backend.PADDLE_PACKAGE', 'paddlepaddle==3.3.0' if change == 'paddle' else backend.PADDLE_PACKAGE):
                    self.prepare(release, ocr=change != 'disabled')
                self.assertNotEqual((release / '.venv').resolve(), original)
                self.assertTrue((original / '.complete').exists())
                self.assertEqual((first / '.venv').resolve(), original)

    def test_failed_install_is_not_published_or_reused(self):
        first = self.release()
        def fail_install(*args, **kwargs):
            if 'install' in args:
                raise subprocess.CalledProcessError(1, args)
            return self.command(*args, **kwargs)
        self.run.side_effect = fail_install
        with self.assertRaises(subprocess.CalledProcessError):
            self.prepare(first)
        self.assertFalse((first / '.venv').is_symlink())
        self.assertEqual(list((self.root / 'shared/python-envs').iterdir()), [])
        self.run.side_effect = self.command
        second = self.release()
        self.prepare(second)
        self.assertTrue((second / '.venv/.complete').is_file())

    def test_interrupted_incomplete_environment_is_rebuilt(self):
        first = self.release()
        self.prepare(first)
        environment = (first / '.venv').resolve()
        # 模拟安装完成标记尚未写入、也尚未供版本引用时中断。
        (first / '.venv').unlink()
        (environment / '.complete').unlink()
        (environment / 'partial').touch()
        self.run.reset_mock()
        second = self.release()
        self.prepare(second)
        self.assertFalse((environment / 'partial').exists())
        self.assertTrue(any('install' in call.args for call in self.run.call_args_list))

    def test_broken_completed_environment_is_not_repaired_in_place(self):
        first = self.release()
        self.prepare(first)
        environment = (first / '.venv').resolve()
        def fail_check(*args, **kwargs):
            if 'check' in args:
                raise subprocess.CalledProcessError(1, args)
            return self.command(*args, **kwargs)
        self.run.reset_mock()
        self.run.side_effect = fail_check
        second = self.release()
        with self.assertRaises(subprocess.CalledProcessError):
            self.prepare(second)
        self.assertFalse((second / '.venv').is_symlink())
        self.assertTrue((environment / '.complete').exists())
        self.assertEqual((first / '.venv').resolve(), environment)
        self.assertFalse(any('install' in call.args for call in self.run.call_args_list))


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "app"
        self.old = self.root / "releases/old"
        self.new = self.root / "releases/new"
        self.old.mkdir(parents=True)
        (self.old / ".venv").mkdir()
        (self.old / ".venv/unchanged").write_text("旧依赖")
        (self.new / "deploy").mkdir(parents=True)
        (self.new / "deploy" / backend.SERVICE).write_text("新服务配置")
        (self.new / "deploy/hackathon.slice").write_text("[Slice]\nMemoryMax=8G\n")
        (self.new / "web/dist/assets").mkdir(parents=True)
        (self.new / "web/dist/index.html").write_text("新页面")
        (self.new / "web/dist/assets/app.js").write_text("新脚本")
        (self.old / "web/dist").mkdir(parents=True)
        (self.old / "web/dist/index.html").write_text("旧页面")
        (self.root / "current").symlink_to(self.old, target_is_directory=True)
        (self.root / "shared/data").mkdir(parents=True)
        (self.root / "shared/data/task.json").write_text("已有任务")
        (self.root / "shared/backend.env").write_text("服务配置")
        self.unit = self.root.parent / ".config/systemd/user" / backend.SERVICE
        self.unit.parent.mkdir(parents=True)
        self.unit.write_text("旧服务配置")

    def assert_shared_unchanged(self):
        self.assertEqual((self.root / "shared/backend.env").read_text(), "服务配置")
        self.assertEqual((self.root / "shared/data/task.json").read_text(), "已有任务")
        self.assertEqual((self.old / ".venv/unchanged").read_text(), "旧依赖")

    @patch("backend.time.sleep")
    @patch("backend.urlopen")
    @patch("backend.wait_healthy")
    @patch("backend.run")
    def test_vl_activation_waits_for_recognition_before_api_restart(self, run, api_health, urlopen, sleep):
        (self.root / "shared/backend.env").write_text(
            "PADDLE_OCR_ENABLED=1\nPADDLE_OCR_ENGINE=vl\nPADDLE_VL_SERVICE_URL=http://127.0.0.1:18082\n")
        for name in backend.MODEL_SERVICES:
            (self.new / "deploy" / name).write_text("新模型服务配置")
        ready = False
        attempts = 0
        def respond(url, **kwargs):
            nonlocal ready, attempts
            if "18082" in url:
                return BytesIO(b'{"status":"ok","pipeline_version":"v1.6","rec_backend":"llama-cpp-server","busy":false}')
            attempts += 1
            if attempts == 1:
                raise HTTPError(url, 503, "Loading model", {}, None)
            ready = True
            return BytesIO(b'{"status":"ok"}')
        def check_restart(*args, **kwargs):
            if args == ("systemctl", "--user", "restart", backend.SERVICE):
                self.assertTrue(ready, "底层模型未就绪时不得启动新 API")
        urlopen.side_effect = respond
        run.side_effect = check_restart
        backend.activate(self.root, self.new)
        self.assertEqual(attempts, 2)
        self.assertEqual((self.root / "current").resolve(), self.new)
        api_health.assert_called_once()

    @patch('backend.wait_healthy')
    @patch('backend.wait_model_healthy', side_effect=RuntimeError('model startup failed'))
    @patch('backend.run')
    def test_vl_startup_failure_restores_api_and_removes_new_model_units(self, run, model_health, api_health):
        config = 'PADDLE_OCR_ENABLED=1\nPADDLE_OCR_ENGINE=vl\nPADDLE_VL_SERVICE_URL=http://127.0.0.1:18082\n'
        (self.root / 'shared/backend.env').write_text(config)
        for name in backend.MODEL_SERVICES:
            (self.new / 'deploy' / name).write_text('new model service')
        with self.assertRaisesRegex(RuntimeError, 'model startup failed'):
            backend.activate(self.root, self.new)
        self.assertEqual((self.root / 'current').resolve(), self.old)
        self.assertEqual(self.unit.read_text(), '旧服务配置')
        self.assertTrue(all(not (self.unit.parent / name).exists() for name in backend.MODEL_SERVICES))
        self.assertEqual((self.root / 'shared/backend.env').read_text(), config)

    @patch("backend.wait_healthy")
    @patch("backend.run")
    def test_success_switches_release_and_retains_rollback_material(self, run, health):
        backend.activate(self.root, self.new)
        self.assertEqual((self.root / "current").resolve(), self.new)
        self.assertEqual(self.unit.read_text(), "新服务配置")
        self.assertEqual((self.new / "previous-service.conf").read_text(), "旧服务配置")
        self.assertEqual((self.new / "previous-release.txt").read_text().strip(), str(self.old))
        self.assert_shared_unchanged()

    @patch("backend.wait_healthy", side_effect=[RuntimeError("启动失败"), None])
    @patch("backend.run")
    def test_unhealthy_release_restores_code_service_and_dependencies(self, run, health):
        with self.assertRaisesRegex(RuntimeError, "启动失败"):
            backend.activate(self.root, self.new)
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assertEqual(self.unit.read_text(), "旧服务配置")
        self.assertEqual(health.call_count, 2)
        self.assert_shared_unchanged()

    @patch("backend.wait_healthy")
    @patch("backend.run")
    def test_failed_restart_also_restores_previous_service(self, run, health):
        run.side_effect = [None, subprocess.CalledProcessError(1, "restart"), None, None, None]
        with self.assertRaises(subprocess.CalledProcessError):
            backend.activate(self.root, self.new)
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assertEqual(self.unit.read_text(), "旧服务配置")
        self.assert_shared_unchanged()

    def test_invalid_release_id_cannot_escape_release_directory(self):
        with self.assertRaises(ValueError):
            backend.deploy(self.root, "../../shared")
        self.assert_shared_unchanged()

    @patch("backend.wait_healthy")
    @patch("backend.run")
    def test_public_probe_failure_can_rollback_activated_release(self, run, health):
        backend.activate(self.root, self.new)
        def check_stop_order(*args, **kwargs):
            if args == ("systemctl", "--user", "stop", backend.SERVICE):
                self.assertEqual(self.unit.read_text(), "新服务配置")
                self.assertEqual((self.root / "current").resolve(), self.new)
        run.side_effect = check_stop_order
        backend.rollback(self.root, self.new)
        self.assertIn(("systemctl", "--user", "stop", backend.SERVICE), [call.args for call in run.call_args_list])
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assertEqual(self.unit.read_text(), "旧服务配置")
        self.assertEqual((self.root / "current/web/dist/index.html").read_text(), "旧页面")
        self.assert_shared_unchanged()

    @patch("backend.run")
    def test_stale_rollback_cannot_replace_a_different_current_release(self, run):
        with self.assertRaisesRegex(RuntimeError, "当前版本已变化"):
            backend.rollback(self.root, self.new)
        run.assert_not_called()
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assert_shared_unchanged()

    @patch("backend.wait_healthy")
    @patch("backend.run")
    def test_rollback_preserves_shared_environment_used_by_both_releases(self, run, health):
        environment = self.root / 'shared/python-envs/complete'
        environment.parent.mkdir()
        (self.old / '.venv').rename(environment)
        (self.old / '.venv').symlink_to(environment, target_is_directory=True)
        (self.new / '.venv').symlink_to(environment, target_is_directory=True)
        backend.activate(self.root, self.new)
        backend.rollback(self.root, self.new)
        self.assertEqual((self.root / 'current').resolve(), self.old)
        self.assertEqual((self.old / '.venv').resolve(), environment)
        self.assertEqual((self.new / '.venv').resolve(), environment)
        self.assert_shared_unchanged()

    @patch("backend.run")
    def test_missing_bootstrap_stops_before_install_or_switch(self, run):
        with self.assertRaisesRegex(RuntimeError, "预先初始化"):
            backend.deploy(self.root, "a" * 40 + "-1-1")
        run.assert_not_called()
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assert_shared_unchanged()

    def prepare_archive(self, settings):
        (self.root / "shared/backend.env").write_text(settings)
        (self.root / "venv/bin").mkdir(parents=True)
        (self.root / "venv/bin/python").touch()
        (self.root / "incoming").mkdir()
        (self.new / "backend").mkdir()
        (self.new / "backend/requirements.txt").write_text('fastapi==0.115.0\n')
        (self.new / "backend/requirements-ocr.txt").write_text('-r requirements.txt\npaddleocr==3.7.0\n')
        release_id = "a" * 40 + "-1-1"
        with tarfile.open(self.root / "incoming" / f"{release_id}.tar.gz", "w:gz") as archive:
            archive.add(self.new, arcname="")
        return release_id

    @patch("backend.activate")
    @patch("backend.run")
    def test_enabled_ocr_uses_selected_python_and_verifies_before_activation(self, run, activate):
        run.return_value.stdout = 'python312'
        settings = 'BACKEND_PYTHON="/opt/python312/bin/python"\nPADDLE_OCR_ENABLED=1\n'
        release_id = self.prepare_archive(settings)
        backend.deploy(self.root, release_id)
        calls = [call.args for call in run.call_args_list]
        venv = next(args for args in calls if "venv" in args)
        self.assertEqual(venv[0], "/opt/python312/bin/python")
        self.assertTrue(any("paddlepaddle==3.2.0" in args for args in calls))
        self.assertTrue(any(str(args[-1]).endswith("requirements-ocr.txt") for args in calls))
        self.assertTrue(any(str(args[1]).endswith("backend/tests/test_paddle_adapter.py") for args in calls if len(args) > 1))
        self.assertTrue(any(str(args[1]).endswith("backend/tools/selftest.py") for args in calls if len(args) > 1))
        probes = [call for call in run.call_args_list if "run_ocr_probe.py" in str(call.args)]
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0].kwargs["env"]["PADDLE_OCR_ENABLED"], "1")
        for call in run.call_args_list:
            if any(name in str(call.args) for name in ("selftest.py", "run_challenge.py", "test_paddle_adapter.py")):
                self.assertEqual(call.kwargs["env"]["PADDLE_OCR_ENABLED"], "0")
        activate.assert_called_once_with(self.root, self.root / "releases" / release_id)
        self.assertEqual((self.root / "shared/backend.env").read_text(), settings)
        self.assertEqual((self.root / "shared/data/task.json").read_text(), "已有任务")

    @patch("backend.activate")
    @patch("backend.run")
    def test_disabled_ocr_keeps_text_only_deployment(self, run, activate):
        run.return_value.stdout = 'python312'
        release_id = self.prepare_archive("PADDLE_OCR_ENABLED=0\n")
        backend.deploy(self.root, release_id)
        calls = [call.args for call in run.call_args_list]
        self.assertTrue(any(str(args[-1]).endswith("backend/requirements.txt") for args in calls))
        self.assertFalse(any("paddlepaddle==3.2.0" in args or "run_ocr_probe.py" in str(args) for args in calls))
        activate.assert_called_once()

    @patch("backend.activate")
    @patch("backend.run")
    def test_missing_frontend_stops_before_dependency_install_and_activation(self, run, activate):
        (self.new / "web/dist/index.html").unlink()
        release_id = self.prepare_archive("PADDLE_OCR_ENABLED=0\n")
        with self.assertRaisesRegex(RuntimeError, "前端构建产物"):
            backend.deploy(self.root, release_id)
        activate.assert_not_called()
        self.assertFalse(any("install" in call.args for call in run.call_args_list))
        self.assertEqual((self.root / "current").resolve(), self.old)

    @patch("backend.activate")
    @patch("backend.run")
    def test_ocr_probe_failure_never_switches_current_release(self, run, activate):
        release_id = self.prepare_archive("PADDLE_OCR_ENABLED=1\n")
        def fail_probe(*args, **kwargs):
            if "run_ocr_probe.py" in str(args):
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0, stdout='python312')
        run.side_effect = fail_probe
        with self.assertRaises(subprocess.CalledProcessError):
            backend.deploy(self.root, release_id)
        activate.assert_not_called()
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assertEqual((self.old / ".venv/unchanged").read_text(), "旧依赖")

    def test_shared_settings_handle_quotes_and_last_assignment(self):
        (self.root / "shared/backend.env").write_text(
            '# PADDLE_OCR_ENABLED=0\nLLM_API_KEY=ignored\n'
            'PADDLE_OCR_ENABLED=0\nPADDLE_OCR_ENABLED="1"\n'
        )
        self.assertEqual(backend.deployment_settings(self.root)["PADDLE_OCR_ENABLED"], "1")

    @patch("backend.activate")
    @patch("backend.run")
    def test_native_vl_is_rejected_before_install(self, run, activate):
        release_id = self.prepare_archive("PADDLE_OCR_ENABLED=1\nPADDLE_OCR_ENGINE=vl\n")
        with self.assertRaisesRegex(ValueError, "8 GiB"):
            backend.deploy(self.root, release_id)
        run.assert_not_called()
        activate.assert_not_called()

    @patch("backend.urlopen")
    @patch("backend.activate")
    @patch("backend.run")
    def test_vl_version_mismatch_never_activates(self, run, activate, urlopen):
        run.return_value.stdout = 'python312'
        from io import BytesIO
        urlopen.return_value = BytesIO(b'{"status":"ok","pipeline_version":"v1.5","busy":false}')
        release_id = self.prepare_archive("PADDLE_OCR_ENABLED=1\nPADDLE_OCR_ENGINE=vl\nPADDLE_VL_SERVICE_URL=http://127.0.0.1:18082\n")
        with self.assertRaisesRegex(RuntimeError, "版本不符"):
            backend.deploy(self.root, release_id)
        activate.assert_not_called()

    @patch("backend.wait_model_healthy", side_effect=RuntimeError("识别模型未就绪"))
    @patch("backend.urlopen")
    @patch("backend.activate")
    @patch("backend.run")
    def test_vl_preflight_requires_recognition_before_probe(self, run, activate, urlopen, readiness):
        run.return_value.stdout = 'python312'
        urlopen.return_value = BytesIO(b'{"status":"ok","pipeline_version":"v1.6","rec_backend":"llama-cpp-server","busy":false}')
        release_id = self.prepare_archive(
            "PADDLE_OCR_ENABLED=1\nPADDLE_OCR_ENGINE=vl\nPADDLE_VL_SERVICE_URL=http://127.0.0.1:18082\n")
        with self.assertRaisesRegex(RuntimeError, "识别模型未就绪"):
            backend.deploy(self.root, release_id)
        readiness.assert_called_once()
        activate.assert_not_called()
        self.assertFalse(any("accept_paddle_vl.py" in str(call.args) for call in run.call_args_list))
        self.assertEqual((self.root / "current").resolve(), self.old)

    @patch("backend.activate")
    @patch("backend.run")
    def test_invalid_ocr_flag_stops_before_install(self, run, activate):
        release_id = self.prepare_archive("PADDLE_OCR_ENABLED=true\n")
        with self.assertRaisesRegex(ValueError, "PADDLE_OCR_ENABLED"):
            backend.deploy(self.root, release_id)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
