"""验证发布与回退不会覆盖运行配置、任务数据或旧版本依赖。"""

from pathlib import Path
import subprocess
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


if __name__ == "__main__":
    unittest.main()
