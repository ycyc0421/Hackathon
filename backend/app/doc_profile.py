"""单证类型 × 应有字段表。

这张表存在的唯一目的：把 `NOT_IN_DOC`（本就不适用）和 `MISSING_IN_DOC`（该有但没找到）分开。
两种状态混在一起，界面会把所有缺失一律报成警告，用户就会忽略全部警告。

商业发票、装箱单、提单按 docs/数据契约.md 第六节已确认的最小规则表。
其余单证类型仍是临时规则，待数据侧（C）提供正式版本后核对。
"""

from __future__ import annotations

from .models import DocType

# 每类单证已确认的必需字段；可选字段缺席不得报 MISSING_IN_DOC。
# 当前对外状态没有「可选但未提供」，因此未出现的可选字段按 NOT_IN_DOC 降级。
DOC_PROFILE: dict[str, set[str]] = {
    DocType.COMMERCIAL_INVOICE.value: {
        "description",
        "quantity",
        "total_amount",
        "currency",
        "invoice_no",
    },
    DocType.PACKING_LIST.value: {
        "description",
        "packages",
        "quantity",
        "gross_weight",
    },
    DocType.BILL_OF_LADING.value: {
        "bill_of_lading_no",
        "description",
        "packages",
        "gross_weight",
    },
    DocType.CUSTOMS_DECLARATION.value: {
        "description",
        "hs_code",
        "packages",
        "quantity",
        "gross_weight",
        "net_weight",
        "total_amount",
        "currency",
        "destination_country",
        "contract_no",
        "container_no",
        "port_of_discharge",
    },
    DocType.CERTIFICATE_OF_ORIGIN.value: {
        "description",
        "hs_code",
        "packages",
        "gross_weight",
        "shipper",
        "consignee",
        "port_of_loading",
        "port_of_discharge",
        "destination_country",
    },
    DocType.INSURANCE_POLICY.value: {
        "total_amount",
        "currency",
        "description",
        "consignee",
        "destination_country",
    },
    # 判不出类型时不臆测，见 profile_of() 的处理
    DocType.OTHER.value: set(),
}


def profile_of(doc_type: str | None) -> set[str] | None:
    """返回该单证类型应有的字段集合。

    返回 None 表示「类型未知」——此时不生成 NOT_IN_DOC 条目，
    免得一份认不出类型的文件凭空刷出十几条「本就不适用」。
    """
    if not doc_type or doc_type == DocType.OTHER.value:
        return None
    return DOC_PROFILE.get(doc_type)


def expects(doc_type: str | None, field_key: str) -> bool:
    prof = profile_of(doc_type)
    if prof is None:
        return False
    return field_key in prof
