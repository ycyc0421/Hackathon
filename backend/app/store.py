"""任务存储。

W1 阶段够用即可：内存字典 + 结果落盘到 .data/tasks/{task_id}.json。
以后要换成 C 的 SQLite，只要替换本文件的读写实现，其余代码不用动。
"""

from __future__ import annotations

import json
import threading
from typing import Optional

from .config import TASK_DIR, ensure_dirs


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._seq = 0
        ensure_dirs()

    # -- 读 ---------------------------------------------------------------
    def get(self, task_id: str) -> Optional[dict]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None and task_id.startswith("tsk_") and all(
                char.isalnum() or char == "_" for char in task_id
            ):
                path = TASK_DIR / f"{task_id}.json"
                if path.is_file():
                    try:
                        task = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        return None
                    if isinstance(task, dict) and task.get("task_id") == task_id:
                        self._tasks[task_id] = task
                    else:
                        return None
            # 返回副本，避免调用方拿到半更新状态
            return json.loads(json.dumps(task)) if task else None

    # -- 写 ---------------------------------------------------------------
    def next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    def create(self, task: dict) -> None:
        with self._lock:
            self._tasks[task["task_id"]] = task

    def update(self, task_id: str, patch: dict) -> None:
        """按顶层键合并更新。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            task.update(patch)

    def persist(self, task_id: str) -> None:
        """把最终结果落盘，便于离线核对与错例复盘。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            payload = json.loads(json.dumps(task))
        ensure_dirs()
        path = TASK_DIR / f"{task_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


store = TaskStore()
