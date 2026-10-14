"""HTTP 接口层。

对外只暴露契约第七节里的三个地址：

    POST /api/v1/checks              创建任务，multipart 上传
    GET  /api/v1/checks/{task_id}    查状态与结果（轮询用同一个）
    GET  /api/v1/evaluation/latest   评测结果

统一错误体：{"error": {"code": "...", "message": "..."}}
失败一律返回非 2xx —— 契约规则 2：不允许用 200 包 success:false，
否则界面会把失败渲染成「检查完成，没有问题」。
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .config import MAX_FILE_COUNT, MAX_FILE_SIZE, POST_WAIT_MS, UPLOAD_DIR, IMAGE_EXT, PADDLE_OCR_ENABLED, llm_enabled, ensure_dirs
from .frontend_view import to_frontend_task
from .models import CheckTask, dump
from .pipeline import rules
from .pipeline.normalize import country_name as country_name_of
from .pipeline.runner import run_check
from .store import store
from .util import make_task_id, now_iso
from . import workflow
from . import rule_sources, evaluation
from .uploads import stage_uploads

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("backend.api")
_check_slots = threading.BoundedSemaphore(4)
_check_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='document-check')


def _run_reserved_check(task_id, uploads):
    try:
        run_check(task_id, uploads)
    finally:
        _check_slots.release()

@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_dirs()
    store.migrate_legacy()
    store.recover_interrupted()
    log.info("规则集版本：%s", rules.rule_version())
    yield


app = FastAPI(
    title="跨境单证合规校验 · 后端接口",
    version=__version__,
    description="数据结构以 docs/schema/check-task.schema.json 为唯一事实来源。",
    lifespan=lifespan,
)

# 开发期允许跨域：D 的前端跑在 Vite 的另一个端口上
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# 统一错误
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


@app.exception_handler(ApiError)
async def _handle_api_error(_request, exc: ApiError) -> JSONResponse:
    return _error_response(exc.status_code, exc.code, exc.message)

@app.exception_handler(workflow.WorkflowError)
async def _handle_workflow(_request, exc):
    return _error_response(exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def _handle_validation(_request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI 默认返回 422，但契约把 422 留给「文件无法解析」，参数错用 400
    detail = "; ".join(
        f"{'.'.join(str(x) for x in e.get('loc', []))}: {e.get('msg', '')}" for e in exc.errors()
    )
    return _error_response(400, "INVALID_REQUEST", f"请求参数有误：{detail}")


@app.exception_handler(StarletteHTTPException)
async def _handle_http(_request, exc: StarletteHTTPException) -> JSONResponse:
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
    return _error_response(exc.status_code, code, str(exc.detail))


@app.exception_handler(Exception)
async def _handle_unexpected(_request, exc: Exception) -> JSONResponse:
    log.exception("未捕获的异常")
    return _error_response(500, "INTERNAL_ERROR", "服务端内部错误，请查看后端日志")


# --------------------------------------------------------------------------
# 基础
# --------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    from .config import BASE_DIR
    revision = BASE_DIR.parent.name.split('-')[0]
    return {"status": "ok", "version": __version__,
            'release_revision': revision if re.fullmatch(r'[0-9a-f]{40}', revision) else None}


@app.get('/api/v1/capabilities')
def capabilities() -> dict:
    from .config import PADDLE_OCR_ENGINE, PADDLE_VL_VERSION, PADDLE_VL_DEVICE
    return {
        'version': __version__,
        'upload_limits': {'max_file_count': MAX_FILE_COUNT, 'max_file_size_bytes': MAX_FILE_SIZE},
        'formats': [
            {'format': 'PDF', 'extensions': ['.pdf'], 'supported': True,
             'text_layer': True, 'scan_ocr_configured': PADDLE_OCR_ENABLED or llm_enabled()},
            {'format': 'IMAGE', 'extensions': sorted(IMAGE_EXT),
             'supported': PADDLE_OCR_ENABLED or llm_enabled()},
            {'format': 'hackathon-trade-json-v1', 'extensions': ['.json'], 'supported': True,
             'encoding': 'UTF-8', 'max_file_size_bytes': 1048576, 'max_line_items': 200},
            {'format': 'UN/EDIFACT', 'extensions': ['.edi'], 'supported': False,
             'reason': '解析器尚未接入；项目 JSON 不代表 EDIFACT 支持'},
            {'format': 'X12', 'extensions': ['.x12'], 'supported': False},
        ],
        'extension_case_sensitive': False,
        'txt_as_edi_supported': False,
        'original_download': True,
        'ocr': {'enabled': PADDLE_OCR_ENABLED, 'engine': PADDLE_OCR_ENGINE,
                'pipeline_version': PADDLE_VL_VERSION if PADDLE_OCR_ENGINE == 'vl' else None,
                'device': PADDLE_VL_DEVICE if PADDLE_OCR_ENGINE == 'vl' else None},
    }


# --------------------------------------------------------------------------
# POST /api/v1/checks
# --------------------------------------------------------------------------
async def _read_limited(upload: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FILE_SIZE:
            mb = MAX_FILE_SIZE // (1024 * 1024)
            raise ApiError(413, "FILE_TOO_LARGE", f"{upload.filename} 超过单文件 {mb}MB 限制")
        chunks.append(chunk)
    return b"".join(chunks)


@app.post("/api/v1/checks")
async def create_check(
    files: list[UploadFile] = File(..., description="同一票货物的多份单证"),
    destination_country: str = Form(..., description="ISO 3166-1 alpha-2，如 DE"),
    destination_country_name: str | None = Form(None),
    trade_mode: str | None = Form(None),
    declared_currency: str | None = Form(None),
    notes: str | None = Form(None),
) -> dict:
    code = (destination_country or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", code):
        raise ApiError(
            400, "INVALID_DESTINATION_COUNTRY", "destination_country 需为两位国家代码，如 DE"
        )

    if declared_currency:
        declared_currency = declared_currency.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", declared_currency):
            raise ApiError(400, "INVALID_CURRENCY", "declared_currency 需为三位币种代码，如 USD")
    else:
        declared_currency = None

    if not files:
        raise ApiError(400, "NO_FILE", "至少上传一份单证")
    if len(files) > MAX_FILE_COUNT:
        raise ApiError(413, "TOO_MANY_FILES", f"一次最多上传 {MAX_FILE_COUNT} 份文件")

    if not _check_slots.acquire(blocking=False):
        raise ApiError(429, 'CHECK_QUEUE_FULL', '已有四票任务正在处理或排队，请稍后重试')
    try:
        uploads: list[tuple[str, bytes]] = []
        for upload in files:
            name = re.split(r'[\\/]', upload.filename or 'unnamed')[-1] or 'unnamed'
            uploads.append((name, await _read_limited(upload)))

        task_id = make_task_id(store.next_seq())
        try:
            documents = stage_uploads(UPLOAD_DIR, task_id, uploads)
        except (OSError, ValueError) as exc:
            log.error('原件持久化失败：%s', exc)
            raise ApiError(500, 'SOURCE_SAVE_FAILED', '原件保存失败，任务未开始处理，请稍后重试') from exc
        store.create(
            {
                "task_id": task_id,
                "status": "PENDING",
                "created_at": now_iso(),
                "finished_at": None,
                "input": {
                    "destination_country": code,
                    "destination_country_name": destination_country_name or country_name_of(code),
                    "trade_mode": trade_mode,
                    "declared_currency": declared_currency,
                    "notes": notes,
                },
                "documents": documents,
                "extractions": [],
                "comparisons": [],
                "risks": [],
                "summary": {
                    "document_count": len(documents),
                    "field_count": 0,
                    "item_count": 0,
                    "conflict_count": 0,
                    "missing_count": 0,
                    "risk_count": 0,
                    "unrecognized_count": 0,
                },
                "errors": [],
            }
        )

        staged = [(name, UPLOAD_DIR / task_id / f'f{index}.source') for index, (name, _) in enumerate(uploads, 1)]
        _check_executor.submit(_run_reserved_check, task_id, staged)
        del uploads

    except BaseException:
        _check_slots.release()
        raise

    # 在 POST_WAIT_MS 内跑完就直接给结果，没跑完就让前端按契约轮询。
    # 两种前端（同步式 / 轮询式）都能直接对接。
    deadline = time.monotonic() + POST_WAIT_MS / 1000
    while time.monotonic() < deadline:
        current = store.get(task_id) or {}
        if current.get("status") not in ("PENDING", "PROCESSING"):
            break
        await asyncio.sleep(0.05)

    return to_frontend_task(dump(_load_task(task_id)))


# --------------------------------------------------------------------------
# GET /api/v1/checks/{task_id}
# --------------------------------------------------------------------------
def _load_task(task_id: str) -> CheckTask:
    task = store.get(task_id)
    if task is None:
        raise ApiError(404, "TASK_NOT_FOUND", f"任务不存在：{task_id}")
    try:
        return CheckTask.model_validate(task)
    except ValidationError as exc:
        log.error("任务 %s 的产出不符合契约：%s", task_id, exc)
        raise ApiError(
            500, "CONTRACT_VIOLATION", "服务端产出不符合数据契约，已阻断返回，请查看后端日志"
        ) from exc


@app.get("/api/v1/checks/{task_id}")
def get_check(task_id: str) -> dict:
    return to_frontend_task(dump(_load_task(task_id)))


@app.get('/api/v1/checks/{task_id}/files/{file_id}')
def download_original(task_id: str, file_id: str):
    task = dump(_load_task(task_id))
    document = next((doc for doc in task['documents'] if doc['file_id'] == file_id), None)
    if document is None:
        raise ApiError(404, 'FILE_NOT_FOUND', '任务中没有该文件')
    if re.search(r'[\\/]', document['file_name']):
        raise ApiError(404, 'SOURCE_NOT_AVAILABLE', '保存的文件名无效，不能读取原件')
    history = store.correction_history(task_id)
    source_id = history[0]['source_task_id'] if history else task_id
    source_dir = (UPLOAD_DIR / source_id).resolve()
    root = UPLOAD_DIR.resolve()
    path = (source_dir / f'{file_id}.source').resolve()
    if not path.is_file():
        # Preserve downloads for previously completed and derived tasks.
        path = (source_dir / f"{file_id}_{document['file_name']}").resolve()
    if not source_dir.is_relative_to(root) or not path.is_relative_to(source_dir) or not path.is_file():
        raise ApiError(404, 'SOURCE_NOT_AVAILABLE', '原件未保存或已移除；不能从抽取结果重建原件')
    return FileResponse(path, media_type='application/octet-stream', filename=document['file_name'],
                        headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store'})

@app.get('/api/v1/checks/{task_id}/corrections')
def get_corrections(task_id: str):
    task = dump(_load_task(task_id))
    return {'task_id':task_id,'result_hash':workflow.payload_hash(task),'corrections':store.correction_history(task_id)}

@app.post('/api/v1/checks/{task_id}/corrections')
def create_correction(task_id: str, request: workflow.CorrectionRequest):
    _load_task(task_id)
    return to_frontend_task(workflow.correct(store,task_id,request))

@app.get('/api/v1/checks/{task_id}/report')
def export_report(task_id: str, format: str = 'json', view: str = 'content'):
    if format == 'html':
        raise ApiError(410, 'REPORT_PRESENTATION_MOVED', '请在报告页面使用前端打印或导出；后端提供结构化 JSON 内容')
    if format != 'json' or view not in {'content', 'archive'}:
        raise ApiError(400, 'INVALID_REPORT_FORMAT', '报告支持 format=json，view=content 或 archive')
    envelope = workflow.report(store, task_id, view=view)
    safe_id = re.sub(r'[^A-Za-z0-9_-]', '_', task_id)
    headers = {'Content-Disposition': f'attachment; filename="{safe_id}-{view}.json"',
               'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store'}
    return JSONResponse(envelope, headers=headers)


@app.get('/api/v1/rules/sources')
def get_rule_source_status():
    return rule_sources.status()


# --------------------------------------------------------------------------
# GET /api/v1/evaluation/latest
# --------------------------------------------------------------------------
@app.get("/api/v1/evaluation/latest")
def latest_evaluation() -> dict:
    return evaluation.latest()


@app.get("/api/v1/evaluation/runs")
def evaluation_history() -> list:
    return evaluation.history()


@app.get("/")
def index() -> dict:
    return {
        "service": "cross-border doc compliance backend",
        "version": __version__,
        "endpoints": [
            "POST /api/v1/checks",
            "GET  /api/v1/checks/{task_id}",
            "GET  /api/v1/evaluation/latest",
            "GET  /api/v1/capabilities",
            "GET  /api/v1/checks/{task_id}/files/{file_id}",
            "GET  /health",
        ],
        "docs": "/docs",
    }
