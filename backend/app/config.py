"""运行时配置。全部可通过环境变量覆盖，见 backend/.env.example。"""

from __future__ import annotations

import os
from datetime import timedelta, timezone
from pathlib import Path

# backend/ 目录
BASE_DIR = Path(__file__).resolve().parent.parent

# 上传文件与任务结果的落盘位置（已在 .gitignore 中忽略）
DATA_DIR = BASE_DIR / ".data"
UPLOAD_DIR = DATA_DIR / "uploads"
TASK_DIR = DATA_DIR / "tasks"

# ---- 时间 ----------------------------------------------------------------
# 契约要求 ISO 8601 且必须带时区。默认 +08:00（团队所在地）。
# 用固定偏移而非 IANA 时区，避免 Windows 上缺 tzdata 时报错。
TZ_OFFSET_HOURS = float(os.getenv("TZ_OFFSET_HOURS", "8"))
TZ = timezone(timedelta(hours=TZ_OFFSET_HOURS))

# ---- 上传限制 ------------------------------------------------------------
# 契约第四节第 11 项：暂按 20MB、10 份。D 的前端也按这个值做前置校验。
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "20")) * 1024 * 1024
MAX_FILE_COUNT = int(os.getenv("MAX_FILE_COUNT", "10"))

# PDF 文本层少于这么多字符时，视为「没有文本层」（很可能是扫描件），转走兜底通道
MIN_TEXT_LAYER_CHARS = int(os.getenv("MIN_TEXT_LAYER_CHARS", "40"))

# ---- 任务形态 ------------------------------------------------------------
# POST /api/v1/checks 之后，最多等待流水线完成 POST_WAIT_MS 毫秒：
#   在时限内跑完 -> 直接返回 COMPLETED / PARTIAL，前端无需轮询也能拿到结果
#   没跑完       -> 返回 PROCESSING，前端按契约轮询 GET /api/v1/checks/{task_id}
# 两种前端（同步式 / 轮询式）都能直接对接。
POST_WAIT_MS = int(os.getenv("POST_WAIT_MS", "1500"))

# ---- 多模态大模型兜底（可选）------------------------------------------------
# 对应分工方案里的「三条硬约定」：OCR 若受阻，直接调多模态大模型 API 保主线交付。
# 不配置时，图片与无文本层 PDF 会被显式标记为 FAILED，不会伪造结果。
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")  # 如 https://api.openai.com/v1
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")  # 如 gpt-4o-mini / qwen-vl-max
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))


def llm_enabled() -> bool:
    """三件套齐全才算启用兜底通道。"""
    return bool(LLM_BASE_URL and LLM_API_KEY and LLM_MODEL)


# ---- 文件类型 ------------------------------------------------------------
PDF_EXT = {".pdf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
EDI_EXT = {".edi", ".txt"}


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOAD_DIR, TASK_DIR):
        d.mkdir(parents=True, exist_ok=True)
