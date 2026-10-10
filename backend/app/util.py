"""小工具：时间戳与 ID 生成。"""

from __future__ import annotations

import random
import string
import uuid
from datetime import datetime

from .config import TZ


def now_iso() -> str:
    """契约要求 ISO 8601 带时区，例：2026-10-12T14:30:00+08:00。"""
    return datetime.now(TZ).isoformat(timespec="seconds")


def today_stamp() -> str:
    return datetime.now(TZ).strftime("%Y%m%d")


def make_task_id(seq: int) -> str:
    """日期与序号便于排查，随机后缀避免服务重启后复用任务 ID。"""
    return f"tsk_{today_stamp()}_{seq:04d}_{uuid.uuid4().hex[:12]}"


def make_file_id(index: int) -> str:
    """例：f1、f2 …… 与 fixtures 保持一致，按上传顺序编号。"""
    return f"f{index}"


def short_rand(n: int = 4) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))
