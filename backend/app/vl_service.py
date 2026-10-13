"""Local VL worker, kept outside the API process memory budget."""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from . import config
from .pipeline.paddle_reader import _run_executor
from .pipeline.paddle_vl_reader import _get_model, recognize_image

_busy = asyncio.Lock()


@asynccontextmanager
async def lifespan(app):
    if config.PADDLE_VL_SERVICE_URL:
        raise RuntimeError('模型进程 PADDLE_VL_SERVICE_URL 必须为空，避免递归调用')
    await asyncio.wrap_future(_run_executor.submit(_get_model))
    yield


app = FastAPI(title='PaddleOCR-VL local worker', lifespan=lifespan)


@app.get('/health')
def health():
    return {'status': 'ok', 'pipeline_version': config.PADDLE_VL_VERSION,
            'device': config.PADDLE_VL_DEVICE, 'rec_backend': config.PADDLE_VL_REC_BACKEND,
            'busy': _busy.locked()}


@app.post('/parse')
async def parse(request: Request):
    if _busy.locked():
        return JSONResponse(status_code=503, content={'error': {'code': 'MODEL_BUSY', 'message': '主模型正在处理其他任务，请稍后重试'}})
    async with _busy:
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > config.MAX_FILE_SIZE:
                return JSONResponse(status_code=413, content={'error': {'code': 'FILE_TOO_LARGE'}})
            chunks.append(chunk)
        future = asyncio.wrap_future(_run_executor.submit(recognize_image, b''.join(chunks)))
        try:
            result = await asyncio.shield(future)
        except asyncio.CancelledError:
            # Do not advertise idle while the native inference is still running.
            await asyncio.shield(future)
            raise
        return {'pipeline_version': config.PADDLE_VL_VERSION, 'failed': result.failed,
                'error_message': result.error_message, 'outputs': result.model_outputs}
