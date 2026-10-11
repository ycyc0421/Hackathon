"""验证发布与回退不会覆盖运行配置、任务数据或旧版本依赖。"""

from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import backend


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
        run.side_effect = [None, subprocess.CalledProcessError(1, "restart"), None, None]
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
        backend.rollback(self.root, self.new)
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assertEqual(self.unit.read_text(), "旧服务配置")
        self.assert_shared_unchanged()

    @patch("backend.run")
    def test_stale_rollback_cannot_replace_a_different_current_release(self, run):
        with self.assertRaisesRegex(RuntimeError, "当前版本已变化"):
            backend.rollback(self.root, self.new)
        run.assert_not_called()
        self.assertEqual((self.root / "current").resolve(), self.old)
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
        release_id = "a" * 40 + "-1-1"
        with tarfile.open(self.root / "incoming" / f"{release_id}.tar.gz", "w:gz") as archive:
            archive.add(self.new, arcname="")
        return release_id

    @patch("backend.activate")
    @patch("backend.run")
    def test_enabled_ocr_uses_selected_python_and_verifies_before_activation(self, run, activate):
        settings = 'BACKEND_PYTHON="/opt/python312/bin/python"\nPADDLE_OCR_ENABLED=1\n'
        release_id = self.prepare_archive(settings)
        backend.deploy(self.root, release_id)
        calls = [call.args for call in run.call_args_list]
        venv = next(args for args in calls if "venv" in args)
        self.assertEqual(venv[0], "/opt/python312/bin/python")
        self.assertTrue(any("paddlepaddle==3.2.0" in args for args in calls))
        self.assertTrue(any(str(args[-1]).endswith("requirements-ocr.txt") for args in calls))
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
        release_id = self.prepare_archive("PADDLE_OCR_ENABLED=0\n")
        backend.deploy(self.root, release_id)
        calls = [call.args for call in run.call_args_list]
        self.assertTrue(any(str(args[-1]).endswith("backend/requirements.txt") for args in calls))
        self.assertFalse(any("paddlepaddle==3.2.0" in args or "run_ocr_probe.py" in str(args) for args in calls))
        activate.assert_called_once()

    @patch("backend.activate")
    @patch("backend.run")
    def test_ocr_probe_failure_never_switches_current_release(self, run, activate):
        release_id = self.prepare_archive("PADDLE_OCR_ENABLED=1\n")
        def fail_probe(*args, **kwargs):
            if "run_ocr_probe.py" in str(args):
                raise subprocess.CalledProcessError(1, args)
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
    def test_invalid_ocr_flag_stops_before_install(self, run, activate):
        release_id = self.prepare_archive("PADDLE_OCR_ENABLED=true\n")
        with self.assertRaisesRegex(ValueError, "PADDLE_OCR_ENABLED"):
            backend.deploy(self.root, release_id)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
