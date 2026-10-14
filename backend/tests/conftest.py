"""在收集前隔离配置，每个测试使用独立存储和任务执行器。"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import threading

import pytest


def pytest_configure(config):
    temporary = TemporaryDirectory(prefix="backend-tests-")
    config.add_cleanup(temporary.cleanup)
    patch = pytest.MonkeyPatch()
    config.add_cleanup(patch.undo)
    root = Path(temporary.name)
    # 必须先于 app 的导入，避免收集测试时初始化开发数据库或启用真实模型。
    for name, value in {
        "TASK_DB_PATH": str(root / "collection.db"),
        "RULE_SOURCE_DIR": "",
        "PADDLE_OCR_ENABLED": "0",
        "PADDLE_VL_SERVICE_URL": "",
        "LLM_BASE_URL": "",
        "LLM_API_KEY": "",
        "LLM_MODEL": "",
        "POST_WAIT_MS": "1500",
    }.items():
        patch.setenv(name, value)
    from app import config as settings

    for name, path in {
        "DATA_DIR": root, "UPLOAD_DIR": root / "uploads", "TASK_DIR": root / "legacy",
    }.items():
        patch.setattr(settings, name, path)


@pytest.fixture(autouse=True)
def isolated_backend(tmp_path, monkeypatch):
    from app import config, main, sqlite_store, store as storage
    from app.pipeline import runner

    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
    monkeypatch.setenv("EVALUATION_RESULT_PATH", str(tmp_path / "evaluation.json"))
    monkeypatch.setenv("RULE_SOURCE_DIR", "")
    for module in (config, sqlite_store):
        monkeypatch.setattr(module, "DATA_DIR", tmp_path)
        monkeypatch.setattr(module, "TASK_DIR", tmp_path / "legacy")
    store = sqlite_store.TaskStore(tmp_path / "tasks.db", tmp_path / "legacy")
    for module in (storage, main, runner):
        monkeypatch.setattr(module, "store", store)
    for module in (config, main, runner):
        monkeypatch.setattr(module, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(main, "_check_slots", threading.BoundedSemaphore(4))
    # 在还原补丁和删除目录之前等待任务退出，防止后台任务污染下一条用例。
    with ThreadPoolExecutor(max_workers=2) as executor:
        monkeypatch.setattr(main, "_check_executor", executor)
        yield store


@pytest.fixture
def client(isolated_backend, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    # 强制走轮询路径，接口测试不依赖机器能否在 POST 等待窗口内完成。
    monkeypatch.setattr(main, "POST_WAIT_MS", 0)
    with TestClient(main.app) as client:
        yield client
