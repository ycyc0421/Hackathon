"""将内部行对齐结构映射到 D 已冻结的 CheckTask 契约。"""

from __future__ import annotations

from copy import deepcopy


def _public_item_id(value: str | None) -> str | None:
    return None if value is None else value.replace("itm_", "item_", 1)


def _action(comparison: dict) -> str | None:
    status = comparison["status"]
    if status == "CONFLICT":
        if comparison["field_key"] in {"packages", "quantity", "total_amount", "amount", "gross_weight", "net_weight", "volume", "unit_price"}:
            return "请核对对应单证的原始数值，再确认申报信息。"
        return "请核对对应单证的原始记录，确认后修正不一致的信息。"
    if status == "MISSING_IN_SOME":
        return "请检查原件是否填写该字段，或人工补充核验。"
    if status == "NOT_CHECKED":
        return "当前无法自动判断，请人工复核。"
    return None


def to_frontend_task(task: dict) -> dict:
    """内部 v0.2 保留行结构，对外按现有 items[]/item_id 契约返回。"""
    result = deepcopy(task)
    members = {
        (m["file_id"], m["item_no"]): _public_item_id(item["item_id"])
        for item in result.get("items", []) for m in item.get("members", [])
    }
    result["items"] = [
        {"item_id": _public_item_id(item["item_id"]), "display_name": item["label"]}
        for item in result.get("items", [])
    ]
    for extraction in result.get("extractions", []):
        file_id = extraction["file_id"]
        for field in extraction["fields"]:
            field["item_id"] = None
        for line in extraction.pop("line_items", []):
            item_id = members.get((file_id, line["item_no"]))
            # Unaligned rows still carry evidence; null ownership does not
            # turn them into document-level values (line_no remains present).
            for field in line["fields"]:
                field["item_id"] = item_id
                field["line_no"] = line["item_no"]
                extraction["fields"].append(field)
    for comparison in result.get("comparisons", []):
        comparison.pop("scope", None)
        comparison["item_id"] = _public_item_id(comparison.get("item_id"))
        comparison["suggested_action"] = _action(comparison)
    for risk in result.get("risks", []):
        risk.pop("related_item_ids", None)
        risk["suggested_action"] = None
    for error in result.get("errors", []):
        if error["code"] == "DOC_PARSE_FAILED":
            suggestion = "请重新上传清晰且可读取的文件，或人工核对原件。"
            if suggestion not in error["message"]:
                error["message"] += f" 建议：{suggestion}"
    result.get("summary", {}).pop("item_count", None)
    result["summary"]["field_count"] = sum(len(e["fields"]) for e in result.get("extractions", []))
    return result
