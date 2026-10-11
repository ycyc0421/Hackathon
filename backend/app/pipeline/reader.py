"""读文件：把 PDF / 图片变成一段纯文本，交给抽取层。

两条通道：
  TEXT_LAYER —— PDF 自带文本层，直接读（快、准、不花钱）
  OCR        —— 图片，或没有文本层的扫描版 PDF，调多模态大模型保真转写

兜底通道未配置时（见 config.llm_enabled），**显式返回失败**，绝不用空文本
冒充「解析成功」—— 契约规则 2：失败必须显式。
"""

from __future__ import annotations

import base64
import struct
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from ..config import (
    IMAGE_EXT,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_TIMEOUT,
    MIN_TEXT_LAYER_CHARS,
    PADDLE_OCR_ENABLED,
    PDF_EXT,
    llm_enabled,
)
from ..models import FileType, ParseMethod

# 保真转写，不做抽取、不翻译、不总结 —— 抽取统一交给 extract.py 的正则，
# 保证「文本层」与「OCR」两条通道走的是同一套抽取逻辑。
TRANSCRIBE_PROMPT = (
    "请逐行转写这张单证图片中的全部可见文字。要求：\n"
    "1. 保持原有的字段标签与数值顺序，例如 'G.W.: 2,400.00 KGS'；\n"
    "2. 不要翻译、不要总结、不要解释、不要补全看不清的内容；\n"
    "3. 看不清的字符原样输出为 * ；\n"
    "4. 只输出转写文本本身。"
)


@dataclass
class ReadResult:
    text: str = ""
    page_count: int | None = None
    parse_method: ParseMethod | None = None
    error_message: str | None = None
    failed: bool = False
    uncertain_item_codes: list[str] = field(default_factory=list)
    ocr_corrections: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def guess_file_type(filename: str) -> FileType:
    ext = Path(filename).suffix.lower()
    if ext in PDF_EXT:
        return FileType.PDF
    if ext in IMAGE_EXT:
        return FileType.IMAGE
    return FileType.OTHER


def read_document(filename: str, data: bytes) -> ReadResult:
    """入口：按文件类型分流。"""
    file_type = guess_file_type(filename)
    if file_type is FileType.PDF:
        return _read_pdf(data)
    if file_type is FileType.IMAGE:
        return _read_image(data)
    return ReadResult(
        error_message=f"暂不支持的文件格式：{Path(filename).suffix or '（无扩展名）'}",
        failed=True,
    )


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def _pdf_image_coverage(page) -> float:
    """按页面上实际绘制的范围识别扫描正文，不用图片像素数判断 logo。"""
    from pypdf import Transformation
    from pypdf.generic import ContentStream

    crop = tuple(float(v) for v in page.cropbox)
    page_area = (crop[2] - crop[0]) * (crop[3] - crop[1])
    image_boxes: set[tuple[float, float, float, float]] = set()

    def bounds(matrix, box):
        points = [matrix.apply_on((x, y)) for x in (box[0], box[2]) for y in (box[1], box[3])]
        return (min(p[0] for p in points), min(p[1] for p in points),
                max(p[0] for p in points), max(p[1] for p in points))

    def intersect(a, b):
        return max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])

    def walk(stream, resources, matrix, clip, ancestors):
        stack = []
        for operands, operator in ContentStream(stream, page.pdf).operations:
            if operator == b"q":
                stack.append(matrix)
            elif operator == b"Q":
                matrix = stack.pop()
            elif operator == b"cm":
                matrix = Transformation(tuple(float(v) for v in operands)).transform(matrix)
            elif operator == b"INLINE IMAGE":
                image_boxes.add(intersect(bounds(matrix, (0, 0, 1, 1)), clip))
            elif operator == b"Do":
                obj = resources["/XObject"][operands[0]].get_object()
                if obj.get("/Subtype") == "/Image":
                    image_boxes.add(intersect(bounds(matrix, (0, 0, 1, 1)), clip))
                elif obj.get("/Subtype") == "/Form":
                    if id(obj) in ancestors:
                        raise ValueError("PDF 图像资源存在循环引用")
                    form_matrix = Transformation(obj.get("/Matrix", (1, 0, 0, 1, 0, 0))).transform(matrix)
                    form_clip = intersect(bounds(form_matrix, obj["/BBox"]), clip)
                    form_resources = obj["/Resources"] if "/Resources" in obj else resources
                    walk(obj, form_resources, form_matrix, form_clip, ancestors | {id(obj)})

    walk(page.get_contents(), page["/Resources"] if "/Resources" in page else {}, Transformation(), crop, set())
    # 按外接矩形保守估算，复杂裁剪或重叠可能多算；疑似正文交给 OCR。
    # 同一范围的重复绘制不重复计数；正文分成多个图块时累加其占比。
    area = sum(max(0, right - left) * max(0, top - bottom) for left, bottom, right, top in image_boxes)
    return area / page_area


def _read_pdf(data: bytes) -> ReadResult:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001
                return ReadResult(error_message="PDF 已加密，无法读取", failed=True)

        page_count = len(reader.pages)
        chunks: list[str] = []
        unreadable_pages: list[int] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text() or ""
                image_coverage = _pdf_image_coverage(page)
                # 图片占据至少五分之一页面时保守走 OCR，页眉再长也不能代表正文已读。
                # 小 logo 仅在本页文本不足时沿用扫描页检查。
                if image_coverage >= 0.2 or (image_coverage > 0 and len(page_text.strip()) < MIN_TEXT_LAYER_CHARS):
                    unreadable_pages.append(index)
                chunks.append(page_text)
            except Exception:  # noqa: BLE001
                unreadable_pages.append(index)
                chunks.append("")
        text = "\n".join(chunks).strip()
    except Exception as exc:  # noqa: BLE001
        return ReadResult(error_message=f"PDF 解析失败：{exc}", failed=True)

    if unreadable_pages:
        if PADDLE_OCR_ENABLED:
            images = _pdf_pages_to_images(data)
            if images is None:
                return ReadResult(page_count=page_count, error_message="PaddleOCR 处理扫描页需要 pymupdf", failed=True)
            from .paddle_reader import read_image as paddle_read_image
            uncertain_codes: list[str] = []
            corrections: list[str] = []
            for index in unreadable_pages:
                recognized = paddle_read_image(images[index - 1][1])
                if not recognized.ok:
                    return ReadResult(page_count=page_count, error_message=f"PDF 第 {index} 页：{recognized.error_message}", failed=True)
                chunks[index - 1] = recognized.text
                uncertain_codes.extend(recognized.uncertain_item_codes)
                corrections.extend(recognized.ocr_corrections)
            return ReadResult(text="\n".join(chunks).strip(), page_count=page_count, parse_method=ParseMethod.OCR, uncertain_item_codes=uncertain_codes, ocr_corrections=corrections)
        if llm_enabled():
            images = _pdf_pages_to_images(data)
            if images is not None:
                return _transcribe_with_llm(images, page_count=page_count)
        return ReadResult(
            page_count=page_count,
            error_message=f"PDF 第 {', '.join(map(str, unreadable_pages))} 页含未读取的图片或解析失败；整份文件未完成识别",
            failed=True,
        )

    if len(text) >= MIN_TEXT_LAYER_CHARS:
        return ReadResult(text=text, page_count=page_count, parse_method=ParseMethod.TEXT_LAYER)

    # 没有文本层 —— 多半是扫描件
    if PADDLE_OCR_ENABLED:
        images = _pdf_pages_to_images(data)
        if images is None:
            return ReadResult(page_count=page_count, error_message="PaddleOCR 处理扫描 PDF 需要 pymupdf", failed=True)
        from .paddle_reader import read_image as paddle_read_image
        chunks = []
        uncertain_codes: list[str] = []
        corrections: list[str] = []
        for index, (_, image) in enumerate(images, start=1):
            recognized = paddle_read_image(image)
            if not recognized.ok:
                return ReadResult(page_count=page_count, error_message=f"PDF 第 {index} 页：{recognized.error_message}", failed=True)
            chunks.append(recognized.text)
            uncertain_codes.extend(recognized.uncertain_item_codes)
            corrections.extend(recognized.ocr_corrections)
        return ReadResult(text="\n".join(chunks), page_count=page_count, parse_method=ParseMethod.OCR, uncertain_item_codes=uncertain_codes, ocr_corrections=corrections)

    if not llm_enabled():
        return ReadResult(
            page_count=page_count,
            error_message=(
                "未检测到文本层（疑似扫描件），且未配置多模态大模型兜底。"
                "请在 .env 中配置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL。"
            ),
            failed=True,
        )

    images = _pdf_pages_to_images(data)
    if images is None:
        return ReadResult(
            page_count=page_count,
            error_message=(
                "未检测到文本层，且缺少 PDF 转图片能力（pip install pymupdf）"
            ),
            failed=True,
        )
    return _transcribe_with_llm(images, page_count=page_count)


def _pdf_pages_to_images(data: bytes) -> list[tuple[str, bytes]] | None:
    """扫描版 PDF 需要先渲染成图。依赖可选的 pymupdf。"""
    try:
        import pymupdf as fitz
    except ImportError:
        return None

    images: list[tuple[str, bytes]] = []
    doc = fitz.open(stream=data, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        images.append(("image/png", pix.tobytes("png")))
    doc.close()
    return images


# --------------------------------------------------------------------------
# 图片
# --------------------------------------------------------------------------
def _read_image(data: bytes) -> ReadResult:
    if PADDLE_OCR_ENABLED:
        from .paddle_reader import read_image as paddle_read_image
        return paddle_read_image(data)
    size = _image_size(data)
    if not llm_enabled():
        hint = ""
        if size:
            hint = f"（图像分辨率 {size[0]}×{size[1]}）"
        return ReadResult(
            error_message=(
                f"图片单证需要 OCR 或多模态大模型兜底{hint}，当前未配置 LLM_BASE_URL / "
                "LLM_API_KEY / LLM_MODEL，无法识别版式"
            ),
            failed=True,
        )
    mime = _sniff_mime(data)
    return _transcribe_with_llm([(mime, data)])


def _sniff_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _image_size(data: bytes) -> tuple[int, int] | None:
    """只读文件头拿宽高，用于给出「分辨率过低」这种可读的失败原因。"""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", data[16:24])
            return int(w), int(h)
        if data[:3] == b"\xff\xd8\xff":
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                    h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                    return int(w), int(h)
                seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
                i += 2 + seg_len
    except Exception:  # noqa: BLE001
        return None
    return None


# --------------------------------------------------------------------------
# 多模态兜底
# --------------------------------------------------------------------------
def _transcribe_with_llm(
    images: list[tuple[str, bytes]], page_count: int | None = None
) -> ReadResult:
    try:
        import httpx
    except ImportError:
        return ReadResult(error_message="缺少 httpx 依赖，无法调用多模态接口", failed=True)

    content: list[dict] = [{"type": "text", "text": TRANSCRIBE_PROMPT}]
    for mime, blob in images:
        b64 = base64.b64encode(blob).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.post(
            f"{LLM_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
        text = (body["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:  # noqa: BLE001
        return ReadResult(
            page_count=page_count,
            error_message=f"多模态识别失败：{exc}",
            failed=True,
        )

    if len(text) < MIN_TEXT_LAYER_CHARS:
        return ReadResult(
            page_count=page_count,
            error_message="多模态识别返回内容过少，无法用于抽取",
            failed=True,
        )
    return ReadResult(
        text=text,
        page_count=page_count if page_count is not None else len(images),
        parse_method=ParseMethod.OCR,
    )
