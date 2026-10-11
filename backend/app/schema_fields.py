"""字段清单：`field_key` → 中文名 / value_type / 归一单位。

对应 docs/数据契约.md 第六节。改这里 = 改契约，改前先同步 schema 与前端。
契约第四节第 2 项：`field_key` 命名需与 C 的数据库字段一致 —— 待 C 确认。
"""

from __future__ import annotations

from typing import NamedTuple


class FieldSpec(NamedTuple):
    key: str
    label: str
    value_type: str  # NUMBER / MONEY / CODE / STRING / DATE
    unit: str | None  # 归一单位；MONEY 的实际单位是币种，运行时决定


# 核心可比字段：差异页的主体，跨文件逐项比对
CORE_COMPARABLE: list[FieldSpec] = [
    FieldSpec("packages", "件数", "NUMBER", "CARTON"),
    FieldSpec("gross_weight", "毛重", "NUMBER", "KGS"),
    FieldSpec("net_weight", "净重", "NUMBER", "KGS"),
    FieldSpec("volume", "体积", "NUMBER", "CBM"),
    FieldSpec("quantity", "数量", "NUMBER", "PCS"),
    FieldSpec("hs_code", "HS 编码", "CODE", None),
    FieldSpec("total_amount", "总金额", "MONEY", None),
    FieldSpec("currency", "币种", "CODE", None),
    FieldSpec("description", "货物描述", "STRING", None),
    FieldSpec("invoice_no", "发票号", "STRING", None),
    FieldSpec("shipment_date", "装运日期", "DATE", None),
]

# 单据标识：用于判定多份文件是否属于同一票货物
IDENTIFIERS: list[FieldSpec] = [
    FieldSpec("bill_of_lading_no", "提单号", "STRING", None),
    FieldSpec("contract_no", "合同号", "STRING", None),
    FieldSpec("container_no", "集装箱号", "STRING", None),
    FieldSpec("shipper", "发货人", "STRING", None),
    FieldSpec("consignee", "收货人", "STRING", None),
    FieldSpec("port_of_loading", "起运港", "STRING", None),
    FieldSpec("port_of_discharge", "目的港", "STRING", None),
    FieldSpec("destination_country", "目的国", "STRING", None),
]

# 品名行级字段（v0.2 新增）：只出现在 extractions[].line_items[].fields[] 里。
# 注意：**不要**把它们加进 doc_profile，否则票级会凭空多出十几条「该有没找到」。
# 票级与行级的字段同名不同层，靠所在位置区分。
ITEM_LEVEL: list[FieldSpec] = [
    FieldSpec("item_code", "货号/型号", "CODE", None),
    FieldSpec("description", "货物描述", "STRING", None),
    FieldSpec("hs_code", "HS 编码", "CODE", None),
    FieldSpec("quantity", "数量", "NUMBER", "PCS"),
    FieldSpec("packages", "件数", "NUMBER", "CARTON"),
    FieldSpec("net_weight", "净重", "NUMBER", "KGS"),
    FieldSpec("gross_weight", "毛重", "NUMBER", "KGS"),
    FieldSpec("volume", "体积", "NUMBER", "CBM"),
    FieldSpec("unit_price", "单价", "MONEY", None),
    FieldSpec("amount", "行金额", "MONEY", None),
]

ALL_FIELDS: list[FieldSpec] = CORE_COMPARABLE + IDENTIFIERS + ITEM_LEVEL

BY_KEY: dict[str, FieldSpec] = {f.key: f for f in ALL_FIELDS}

ITEM_LEVEL_BY_KEY: dict[str, FieldSpec] = {f.key: f for f in ITEM_LEVEL}

# 契约第六节的「最小可用集合」：6 项即可覆盖全部 5 种比对状态
MINIMAL_SET = ["packages", "gross_weight", "hs_code", "total_amount", "currency", "description"]

# 必须过规则校验的字段：规则没覆盖时不能报 SINGLE_SOURCE，要报 NOT_CHECKED
RULE_REQUIRED_FIELDS = {"hs_code"}


def label_of(field_key: str) -> str:
    spec = BY_KEY.get(field_key)
    return spec.label if spec else field_key


def value_type_of(field_key: str) -> str:
    spec = BY_KEY.get(field_key)
    return spec.value_type if spec else "STRING"


def unit_of(field_key: str) -> str | None:
    spec = BY_KEY.get(field_key)
    return spec.unit if spec else None
