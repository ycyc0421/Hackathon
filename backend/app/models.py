"""契约的结构化形式（Pydantic v2）。

对应：
- v0.1（官方，只读）：docs/schema/check-task.schema.json
- v0.2（我方提案）：多品名提案/check-task.schema.v0.2.proposed.json

**官方 schema 一个字节都没有改。** v0.2 是我们自己的版本，用于支撑「一票货多品名」；
相对 v0.1 是纯增量，单品名票的既有字段名、类型、语义全部不变，只是多出
items / line_items / scope / item_id / item_count / related_item_ids 这几个键。

两个要点：
1. `extra="forbid"` == schema 里的 `additionalProperties: false`。
   返回体多一个未定义的键，这里就会直接报错 —— 宁可报错，也不静默多加字段。
2. 跨字段约束用 model_validator 实现，例如
   「CONFLICT 时 values 至少 2 条且 severity 不得为 INFO」
   「NOT_CHECKED 时必须给出 note」
   「scope=ITEM 必须有 item_id，scope=DOCUMENT 时 item_id 必须为 null」
   这些约束只能靠代码表达，可读文档里写不出来。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict, Field as PField, model_validator

# 未定义键即报错（== additionalProperties: false）
STRICT = ConfigDict(extra="forbid")

# normalized_value / canonical_value 的取值：字符串、数字、布尔、null
Scalar = Union[str, int, float, bool]
NullableScalar = Optional[Scalar]


# --------------------------------------------------------------------------
# 枚举
# --------------------------------------------------------------------------
class TaskStatus(str, Enum):
    """COMPLETED 与 PARTIAL 必须分开：前者全部分析完成，后者有文件失败但其余出了结果。"""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class DocType(str, Enum):
    """判不出来给 None。"""

    COMMERCIAL_INVOICE = "COMMERCIAL_INVOICE"
    PACKING_LIST = "PACKING_LIST"
    BILL_OF_LADING = "BILL_OF_LADING"
    CUSTOMS_DECLARATION = "CUSTOMS_DECLARATION"
    CERTIFICATE_OF_ORIGIN = "CERTIFICATE_OF_ORIGIN"
    INSURANCE_POLICY = "INSURANCE_POLICY"
    OTHER = "OTHER"


class FileType(str, Enum):
    PDF = "PDF"
    IMAGE = "IMAGE"
    EDI = "EDI"
    OTHER = "OTHER"


class ProcessStatus(str, Enum):
    UPLOADED = "UPLOADED"
    PARSING = "PARSING"
    EXTRACTED = "EXTRACTED"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"


class ParseMethod(str, Enum):
    TEXT_LAYER = "TEXT_LAYER"
    OCR = "OCR"
    EDI_PARSE = "EDI_PARSE"


class FieldStatus(str, Enum):
    """该字段在某一份文件里的状态。NOT_IN_DOC 与 MISSING_IN_DOC 必须分开。"""

    EXTRACTED = "EXTRACTED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    NOT_IN_DOC = "NOT_IN_DOC"
    MISSING_IN_DOC = "MISSING_IN_DOC"
    UNRECOGNIZED = "UNRECOGNIZED"
    NORMALIZE_FAILED = "NORMALIZE_FAILED"


class ComparisonStatus(str, Enum):
    """跨文件比对结论。NOT_CHECKED 必须返回：省略它等于让用户以为检查过了。"""

    MATCH = "MATCH"
    CONFLICT = "CONFLICT"
    MISSING_IN_SOME = "MISSING_IN_SOME"
    NOT_CHECKED = "NOT_CHECKED"
    UNRECOGNIZED = "UNRECOGNIZED"
    SINGLE_SOURCE = "SINGLE_SOURCE"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class RiskType(str, Enum):
    MISSING_CERTIFICATE = "MISSING_CERTIFICATE"
    HS_CLASSIFICATION = "HS_CLASSIFICATION"
    RULE_UNCOVERED = "RULE_UNCOVERED"
    OTHER = "OTHER"


class ErrorLevel(str, Enum):
    FATAL = "FATAL"
    ERROR = "ERROR"
    WARNING = "WARNING"


class ValueType(str, Enum):
    NUMBER = "NUMBER"
    MONEY = "MONEY"
    CODE = "CODE"
    STRING = "STRING"
    DATE = "DATE"


class BBoxUnit(str, Enum):
    PX = "PX"
    RELATIVE = "RELATIVE"


# ---- v0.2 新增 ------------------------------------------------------------
class AlignmentStatus(str, Enum):
    """行组的对齐状态。

    ALIGNED   = 至少两份文件的行已对应上，品名级比对有意义
    PARTIAL   = 只有一份文件有该行，无法比对，但不代表异常（如提单只有汇总）
    UNALIGNED = 多份文件都有疑似行但无法确定对应关系，**不得据此给出比对结论**
    """

    ALIGNED = "ALIGNED"
    PARTIAL = "PARTIAL"
    UNALIGNED = "UNALIGNED"


class AlignmentBasis(str, Enum):
    """对应关系的依据。给不出依据时给 None，不要假装是位置对齐。"""

    ITEM_CODE = "ITEM_CODE"
    DESCRIPTION = "DESCRIPTION"
    POSITION = "POSITION"


class ComparisonScope(str, Enum):
    """DOCUMENT = 票级（沿用 v0.1 语义）；ITEM = 品名级（同一行组内互比）。"""

    DOCUMENT = "DOCUMENT"
    ITEM = "ITEM"


# --------------------------------------------------------------------------
# 任务输入与文件清单
# --------------------------------------------------------------------------
class TaskInput(BaseModel):
    model_config = STRICT
    destination_country: str = PField(pattern=r"^[A-Z]{2}$")
    destination_country_name: Optional[str] = None
    trade_mode: Optional[str] = None
    declared_currency: Optional[str] = PField(default=None, pattern=r"^[A-Z]{3}$")
    notes: Optional[str] = None


class Document(BaseModel):
    model_config = STRICT
    file_id: str
    file_name: str
    file_type: FileType
    doc_type: Optional[DocType] = None
    process_status: ProcessStatus
    page_count: Optional[int] = PField(default=None, ge=1)
    error_message: Optional[str] = None


# --------------------------------------------------------------------------
# 第 1 层：单文件抽取
# --------------------------------------------------------------------------
class ExtractedField(BaseModel):
    """契约里的 `Field`。名字加 Extracted 前缀避免与 pydantic.Field 混淆。

    v0.2 起：同一个 field_key 可以在同一份文件里出现多次 —— 票级一次
    （放在 Extraction.fields），各品名行各一次（放在 LineItem.fields）。
    其身份由**所在位置**决定，不再由 field_key 唯一决定。
    """

    model_config = STRICT
    field_key: str = PField(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    raw_text: Optional[str] = None
    raw_value: Optional[str] = None
    normalized_value: NullableScalar = None
    unit: Optional[str] = None
    confidence: Optional[float] = PField(default=None, ge=0, le=1)
    status: FieldStatus
    page: Optional[int] = PField(default=None, ge=1)
    bbox: Optional[list[float]] = None
    bbox_unit: Optional[BBoxUnit] = None

    @model_validator(mode="after")
    def _check(self) -> "ExtractedField":
        if self.status in (FieldStatus.EXTRACTED, FieldStatus.LOW_CONFIDENCE):
            if self.normalized_value is None:
                raise ValueError(
                    f"{self.field_key}: status={self.status.value} 时 normalized_value 必须有值"
                )
        if self.status in (
            FieldStatus.NOT_IN_DOC,
            FieldStatus.MISSING_IN_DOC,
            FieldStatus.UNRECOGNIZED,
        ):
            if self.normalized_value is not None:
                raise ValueError(
                    f"{self.field_key}: status={self.status.value} 时 normalized_value 必须为 null"
                )
        if self.bbox is not None and len(self.bbox) != 4:
            raise ValueError(f"{self.field_key}: bbox 必须是 [x, y, width, height] 四项")
        return self


class LineItem(BaseModel):
    """一份文件里的一个品名行（v0.2 新增）。

    只放**属于该行**的字段；整票唯一的字段（发票号、港口、收发货人）和
    整票汇总值（各行之和的合计）仍放在 Extraction.fields，不要塞进来。
    """

    model_config = STRICT
    item_no: int = PField(ge=1)
    raw_text: Optional[str] = None
    fields: list[ExtractedField] = PField(default_factory=list)


class Extraction(BaseModel):
    model_config = STRICT
    file_id: str
    doc_type: Optional[DocType] = None
    parse_method: Optional[ParseMethod] = None
    fields: list[ExtractedField] = PField(default_factory=list)
    # 单品名票与无明细单证（如提单）为空数组，**但不省略该键**
    line_items: list[LineItem] = PField(default_factory=list)


# --------------------------------------------------------------------------
# 第 2 层：跨文件比对
# --------------------------------------------------------------------------
class ComparisonValue(BaseModel):
    model_config = STRICT
    file_id: str
    file_name: str
    raw_value: Optional[str] = None
    normalized_value: NullableScalar = None
    field_status: FieldStatus
    page: Optional[int] = PField(default=None, ge=1)
    bbox: Optional[list[float]] = None


class Comparison(BaseModel):
    model_config = STRICT
    comparison_id: str
    scope: ComparisonScope = ComparisonScope.DOCUMENT
    item_id: Optional[str] = None
    field_key: str = PField(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    value_type: ValueType
    unit: Optional[str] = None
    status: ComparisonStatus
    canonical_value: NullableScalar = None
    severity: Severity
    rule_id: Optional[str] = None
    note: Optional[str] = None
    values: list[ComparisonValue] = PField(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "Comparison":
        # 系统不判断哪份文件正确 —— canonical_value 恒为 null
        if self.canonical_value is not None:
            raise ValueError(f"{self.comparison_id}: canonical_value 必须保持 null")
        if self.scope is ComparisonScope.ITEM:
            if not self.item_id:
                raise ValueError(f"{self.comparison_id}: scope=ITEM 必须给出 item_id")
        elif self.item_id is not None:
            raise ValueError(f"{self.comparison_id}: scope=DOCUMENT 时 item_id 必须为 null")
        if self.status is ComparisonStatus.CONFLICT:
            if len(self.values) < 2:
                raise ValueError(f"{self.comparison_id}: CONFLICT 至少需要 2 条 values")
            if self.severity is Severity.INFO:
                raise ValueError(f"{self.comparison_id}: CONFLICT 的 severity 不得为 INFO")
        if self.status is ComparisonStatus.SINGLE_SOURCE and len(self.values) > 1:
            raise ValueError(f"{self.comparison_id}: SINGLE_SOURCE 至多 1 条 values")
        if self.status is ComparisonStatus.NOT_CHECKED:
            if not self.note:
                raise ValueError(f"{self.comparison_id}: NOT_CHECKED 必须给出 note 说明未校验原因")
        return self


# --------------------------------------------------------------------------
# 第 1.5 层：跨文件行对齐（v0.2 新增）
# --------------------------------------------------------------------------
class ItemMember(BaseModel):
    """该行组在某一份文件里对应的那一行。"""

    model_config = STRICT
    file_id: str
    item_no: int = PField(ge=1)
    # 对齐依据的相似度。正则/位置对齐给不出标定值时给 None，不要给假数字
    match_score: Optional[float] = PField(default=None, ge=0, le=1)


class ItemGroup(BaseModel):
    """对齐后的一组相互对应的「行」，品名级比对的最小单位。"""

    model_config = STRICT
    item_id: str
    label: str
    alignment_status: AlignmentStatus
    alignment_basis: Optional[AlignmentBasis] = None
    alignment_note: Optional[str] = None
    members: list[ItemMember] = PField(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "ItemGroup":
        if not self.members:
            raise ValueError(f"{self.item_id}: members 至少 1 条")
        seen: set[str] = set()
        for m in self.members:
            if m.file_id in seen:
                raise ValueError(
                    f"{self.item_id}: 同一份文件在同一行组里最多出现一次（{m.file_id} 重复）"
                )
            seen.add(m.file_id)
        if self.alignment_status is AlignmentStatus.ALIGNED:
            if self.alignment_note is not None:
                raise ValueError(f"{self.item_id}: ALIGNED 时 alignment_note 应为 null")
        elif not self.alignment_note:
            # UNALIGNED / PARTIAL 必须说明原因，否则前端无法向用户解释
            raise ValueError(
                f"{self.item_id}: alignment_status={self.alignment_status.value} 时必须给出 alignment_note"
            )
        return self


# --------------------------------------------------------------------------
# 风险与错误
# --------------------------------------------------------------------------
class Risk(BaseModel):
    model_config = STRICT
    risk_id: str
    type: RiskType
    severity: Severity
    title: str
    detail: str
    related_field_keys: list[str] = PField(default_factory=list)
    # 品名级风险指向具体行组；票级风险给空数组（v0.2 新增）
    related_item_ids: list[str] = PField(default_factory=list)
    related_file_ids: list[str] = PField(default_factory=list)
    destination_country: Optional[str] = None
    rule_id: Optional[str] = None
    rule_source: Optional[str] = None

    @model_validator(mode="after")
    def _check(self) -> "Risk":
        if self.destination_country is not None:
            if len(self.destination_country) != 2 or not self.destination_country.isupper():
                raise ValueError(f"{self.risk_id}: destination_country 需为 ISO 3166-1 alpha-2")
        return self


class TaskError(BaseModel):
    model_config = STRICT
    code: str = PField(pattern=r"^[A-Z][A-Z0-9_]*$")
    message: str
    level: ErrorLevel
    file_ids: list[str] = PField(default_factory=list)


class Summary(BaseModel):
    model_config = STRICT
    document_count: int = PField(ge=0)
    # v0.2 起：= 所有 extractions[].fields 与 extractions[].line_items[].fields 的条目总数
    field_count: int = PField(ge=0)
    item_count: int = PField(ge=0)
    conflict_count: int = PField(ge=0)
    missing_count: int = PField(ge=0)
    risk_count: int = PField(ge=0)
    unrecognized_count: int = PField(ge=0)


# --------------------------------------------------------------------------
# 顶层：一个检查任务
# --------------------------------------------------------------------------
class CheckTask(BaseModel):
    """GET /api/v1/checks/{task_id} 的返回体。"""

    model_config = STRICT
    task_id: str
    status: TaskStatus
    created_at: str
    finished_at: Optional[str] = None
    input: TaskInput
    documents: list[Document] = PField(default_factory=list)
    extractions: list[Extraction] = PField(default_factory=list)
    # 对齐后的行组清单。单品名票为空数组，**但不省略该键**（v0.2 新增）
    items: list[ItemGroup] = PField(default_factory=list)
    comparisons: list[Comparison] = PField(default_factory=list)
    risks: list[Risk] = PField(default_factory=list)
    summary: Summary
    errors: list[TaskError] = PField(default_factory=list)


# --------------------------------------------------------------------------
# 评测
# --------------------------------------------------------------------------
class EvalStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class PRF(BaseModel):
    model_config = STRICT
    precision: Optional[float] = PField(default=None, ge=0, le=1)
    recall: Optional[float] = PField(default=None, ge=0, le=1)
    f1: Optional[float] = PField(default=None, ge=0, le=1)


class Metrics(BaseModel):
    model_config = STRICT
    field_extraction: Optional[PRF] = None
    conflict_detection: Optional[PRF] = None
    risk_hint: Optional[PRF] = None


class Evaluation(BaseModel):
    """GET /api/v1/evaluation/latest 的返回体。设计上就支持「尚未评测」。"""

    model_config = STRICT
    status: EvalStatus
    dataset_version: Optional[str] = None
    sample_count: int = PField(ge=0)
    model_version: Optional[str] = None
    metrics: Optional[Metrics] = None
    error_breakdown: Optional[dict[str, int]] = None
    run_at: Optional[str] = None

    @model_validator(mode="after")
    def _check(self) -> "Evaluation":
        if self.status in (EvalStatus.NOT_RUN, EvalStatus.RUNNING, EvalStatus.FAILED):
            if self.metrics is not None:
                raise ValueError("metrics 仅在 status=DONE 时非 null")
        if self.status is EvalStatus.NOT_RUN:
            if self.run_at is not None:
                raise ValueError("NOT_RUN 不应有 run_at")
        return self


def not_run_evaluation() -> Evaluation:
    """未跑分时的标准返回。界面显示「尚未评测」，不以默认值填充。"""
    return Evaluation(
        status=EvalStatus.NOT_RUN,
        dataset_version=None,
        sample_count=0,
        model_version=None,
        metrics=None,
        run_at=None,
    )


def dump(obj: BaseModel) -> dict[str, Any]:
    """转成可直接返回的 JSON 字典（枚举取字符串值，保留 null）。"""
    return obj.model_dump(mode="json")
