"""任务编排：把 读取 → 抽取 → 比对 → 合规 串起来，产出契约形状的任务对象。

契约规则 2：**失败必须显式。**
所以这里任何一步出问题，都会在 status 与 errors[] 上留痕，不会返回一个
「看起来没问题」的空结果。
"""

from __future__ import annotations

import logging
import traceback

from pydantic import ValidationError

from ..config import UPLOAD_DIR, ensure_dirs
from ..models import CheckTask, dump
from ..store import store
from ..util import make_file_id, now_iso
from . import classify, rules
from .align import align_items
from .compare import build_comparisons, build_item_comparisons
from .extract import extract_fields
from .normalize import normalize_description
from .reader import guess_file_type, read_document
from .rows import parse_line_items

log = logging.getLogger("backend.pipeline")


def _apply_ocr_corrections(line_items: list[dict], corrections: list[dict[str, str]]) -> None:
    """Keep the uncorrected OCR reading as evidence; compare the corrected candidate cautiously."""
    for correction in corrections:
        corrected = normalize_description(correction["corrected"])
        for line in line_items:
            code = next((field.get("raw_value") for field in line["fields"] if field["field_key"] == "item_code"), None)
            if code != correction["item_code"]:
                continue
            for field in line["fields"]:
                # raw_value 已截断为 80 字符；归一值仍保留完整品名。
                if field["field_key"] == "description" and field["normalized_value"] == corrected:
                    field["raw_text"] = correction["original"]
                    field["raw_value"] = correction["original"]
                    field["status"] = "LOW_CONFIDENCE"


def run_check(task_id: str, uploads: list[tuple[str, bytes]]) -> None:
    """在后台线程里跑完一票货的全部处理。"""
    try:
        _run(task_id, uploads)
    except Exception:  # noqa: BLE001
        # 兜底：绝不让任务永远停在 PROCESSING
        log.error("流水线异常\n%s", traceback.format_exc())
        store.update(
            task_id,
            {
                "status": "FAILED",
                "finished_at": now_iso(),
                "errors": [
                    {
                        "code": "INTERNAL_ERROR",
                        "message": "服务端处理异常，请查看后端日志",
                        "level": "FATAL",
                        "file_ids": [],
                    }
                ],
            },
        )
        store.persist(task_id)


def _run(task_id: str, uploads: list[tuple[str, bytes]]) -> None:
    store.update(task_id, {"status": "PROCESSING"})
    task = store.get(task_id)
    if task is None:
        return

    ensure_dirs()
    task_dir = UPLOAD_DIR / task_id

    documents: list[dict] = []
    extractions: list[dict] = []
    items: list[dict] = []  # 第 1.5 层：跨文件行对齐结果（单品名票为空）
    errors: list[dict] = []
    row_unparsed = False  # 有文件的品名明细表没能解析干净

    for index, (filename, data) in enumerate(uploads, start=1):
        file_id = make_file_id(index)
        file_type = guess_file_type(filename)

        # 原件落盘，便于错例复盘（.data/ 已在 .gitignore 中）
        try:
            task_dir.mkdir(parents=True, exist_ok=True)
            (task_dir / f"{file_id}_{filename}").write_bytes(data)
        except Exception:  # noqa: BLE001
            log.warning("上传文件落盘失败：%s", filename)

        # 暂不支持的格式（如 EDI、Word）显式标出，不静默丢弃
        if file_type.value == "OTHER":
            documents.append(
                {
                    "file_id": file_id,
                    "file_name": filename,
                    "file_type": "OTHER",
                    "doc_type": None,
                    "process_status": "UNSUPPORTED",
                    "page_count": None,
                    "error_message": "暂不支持该文件格式，当前仅支持 PDF 与图片",
                }
            )
            errors.append(
                {
                    "code": "UNSUPPORTED_FILE_TYPE",
                    "message": f"{filename} 暂不支持：当前仅支持 PDF 与图片",
                    "level": "WARNING",
                    "file_ids": [file_id],
                }
            )
            continue

        result = read_document(filename, data)

        if not result.ok:
            documents.append(
                {
                    "file_id": file_id,
                    "file_name": filename,
                    "file_type": file_type.value,
                    "doc_type": None,
                    "process_status": "FAILED",
                    "page_count": result.page_count,
                    "error_message": result.error_message,
                }
            )
            errors.append(
                {
                    "code": "DOC_PARSE_FAILED",
                    "message": f"{filename} 解析失败：{result.error_message}",
                    "level": "ERROR",
                    "file_ids": [file_id],
                }
            )
            continue

        doc_type = classify.classify(result.text, filename)
        # 多页 PDF 无法确定字段落在哪一页，page 留 null，不编造
        page = result.page_count if result.page_count == 1 else None

        # 先认表格、把表格区域从票级文本里剥掉：
        # 不剥的话票级会抽到表头和行号（实测过 total_amount 抽成 "1."），
        # 拿着垃圾去比对，会给出一个看起来很正常的错误结论。
        table = parse_line_items(result.text)
        fields = extract_fields(
            table.doc_text, doc_type, page=page, row_keys=table.header_keys or None
        )
        line_items = table.line_items

        if result.ocr_corrections:
            _apply_ocr_corrections(line_items, result.ocr_corrections)
            changes = [f"{c['item_code']}: {c['original']} → {c['corrected']}" for c in result.ocr_corrections]
            errors.append({
                "code": "OCR_AUTO_CORRECTED",
                "message": f"{filename} 的 OCR 数字/字母混淆已按单位格式和另一识别结果校正：{'；'.join(changes)}。原识别值保留在字段证据中，请核对原件。",
                "level": "WARNING",
                "file_ids": [file_id],
            })

        if result.uncertain_item_codes:
            uncertain_codes = set(result.uncertain_item_codes)
            for li in line_items:
                code = next((f.get("raw_value") for f in li["fields"] if f["field_key"] == "item_code"), None)
                if code in uncertain_codes:
                    for f in li["fields"]:
                        if f["field_key"] == "description":
                            f["status"] = "NORMALIZE_FAILED"
                            f["normalized_value"] = None
            errors.append({
                "code": "OCR_TEXT_DISAGREEMENT",
                "message": f"{filename} 的商品品名在普通 OCR 与表格识别中不一致（货号：{', '.join(result.uncertain_item_codes)}），品名级比对待人工复核。",
                "level": "WARNING",
                "file_ids": [file_id],
            })

        if table.suspected:
            row_unparsed = True
            # 列归属不可靠时整份文件的品名行不得参与比对；LOW_CONFIDENCE
            # 仍属于可比值，保留它会产生貌似正常的 MATCH。
            line_items = []
            errors.append(
                {
                    "code": "MULTI_LINE_ITEMS_SUSPECTED",
                    "message": (
                        f"{filename} 里检测到品名明细表，但未能可靠解析出全部品名行，"
                        "该文件的品名级比对未完成，请人工核对表格区域。"
                    ),
                    "level": "WARNING",
                    "file_ids": [file_id],
                }
            )

        # 行金额/单价的单位是币种 —— 取本文件票级抽到的币种填进每一行，
        # 否则金额比对会因为「币种未知」而只能报「无法确认」。
        currency = _currency_of(fields)
        if currency:
            for li in line_items:
                for f in li["fields"]:
                    if f["field_key"] in ("amount", "unit_price") and f["normalized_value"] is not None:
                        f["unit"] = currency

        documents.append(
            {
                "file_id": file_id,
                "file_name": filename,
                "file_type": file_type.value,
                "doc_type": doc_type,
                "process_status": "EXTRACTED",
                "page_count": result.page_count,
                "error_message": None,
            }
        )
        extractions.append(
            {
                "file_id": file_id,
                "doc_type": doc_type,
                "parse_method": result.parse_method.value if result.parse_method else None,
                "fields": fields,
                "line_items": line_items,
            }
        )

    task_input = task["input"]

    # 第 1.5 层：把各文件的品名行对齐成 items[]（单品名票结果为空数组）
    items = align_items(extractions, documents)

    comparisons = build_comparisons(
        documents,
        extractions,
        rules.hs_covered,
        destination_country=task_input.get("destination_country"),
        destination_country_name=task_input.get("destination_country_name"),
    )
    # 品名级比对接在票级之后，comparison_id 连续编号
    comparisons += build_item_comparisons(
        items,
        documents,
        extractions,
        rules.hs_covered,
        destination_country=task_input.get("destination_country"),
        destination_country_name=task_input.get("destination_country_name"),
        start_index=len(comparisons),
    )
    risks = rules.evaluate_risks(task_input, documents, extractions, items)

    # 规则集尚未核实：只要给出了基于规则的提示，就追加一条任务级 WARNING，
    # 免得「未核实的演示规则」被前端和评审当成确定的合规结论。
    if risks and not rules.ruleset_verified():
        errors.append(
            {
                "code": "RULES_UNVERIFIED",
                "message": (
                    "本票合规提示来自团队自拟的演示规则集，来源与适用条件尚未核实，"
                    "不得作为合规依据。"
                ),
                "level": "WARNING",
                "file_ids": [],
            }
        )

    ok_count = sum(1 for d in documents if d["process_status"] == "EXTRACTED")
    if not documents or ok_count == 0:
        status = "FAILED"
        errors.append(
            {
                "code": "ALL_DOCUMENTS_FAILED",
                "message": "全部文件均未能处理成功，无法完成比对与合规校验",
                "level": "FATAL",
                "file_ids": [d["file_id"] for d in documents],
            }
        )
    elif ok_count < len(documents) or row_unparsed:
        # 有文件失败，或有文件的品名明细没能解析干净 —— 必须与「全部成功」区分开
        status = "PARTIAL"
    else:
        status = "COMPLETED"

    # v0.2：field_count 同时计入票级字段与各品名行的字段
    field_count = sum(len(e["fields"]) for e in extractions) + sum(
        len(li["fields"]) for e in extractions for li in e["line_items"]
    )
    summary = {
        "document_count": len(documents),
        "field_count": field_count,
        "item_count": len(items),
        "conflict_count": sum(1 for c in comparisons if c["status"] == "CONFLICT"),
        "missing_count": sum(1 for c in comparisons if c["status"] == "MISSING_IN_SOME"),
        "risk_count": len(risks),
        "unrecognized_count": sum(1 for c in comparisons if c["status"] == "UNRECOGNIZED"),
    }

    payload = {
        "task_id": task_id,
        "status": status,
        "created_at": task["created_at"],
        "finished_at": now_iso(),
        "input": task_input,
        "documents": documents,
        "extractions": extractions,
        "items": items,
        "comparisons": comparisons,
        "risks": risks,
        "summary": summary,
        "errors": errors,
    }

    # 出门前自查一遍：不符合契约就显式失败，绝不把坏数据发给前端
    try:
        CheckTask.model_validate(payload)
    except ValidationError as exc:
        log.error("产出不符合契约：%s", exc)
        store.update(
            task_id,
            {
                "status": "FAILED",
                "finished_at": payload["finished_at"],
                "errors": errors
                + [
                    {
                        "code": "CONTRACT_VIOLATION",
                        "message": "服务端产出不符合数据契约，已阻断返回，请查看后端日志",
                        "level": "FATAL",
                        "file_ids": [],
                    }
                ],
            },
        )
        store.persist(task_id)
        return

    store.update(task_id, dump(CheckTask.model_validate(payload)))
    store.persist(task_id)


def _currency_of(fields: list[dict]) -> str | None:
    """取本文件票级抽到的币种，用作行金额的单位。抽不到给 None，不猜。"""
    for f in fields:
        if f["field_key"] == "currency" and f["status"] in ("EXTRACTED", "LOW_CONFIDENCE"):
            value = f.get("normalized_value")
            if value:
                return str(value)
    return None
