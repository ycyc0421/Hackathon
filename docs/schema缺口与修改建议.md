# Schema 缺口与修改建议

更新时间：2026-10-10

## 当前检查结论

D 端已经接受 `items[]` 方案，确认内容包括：

- 第一版单品名也返回单元素 `items[]`；
- 多品名使用任务内的 `item_id`；
- 比较键为 `item_id + field_key`；
- 整票字段使用 `item_id: null`；
- 商品字段保留文件内行号；
- Schema 增量 PR 将增加顶层 `items[]`、`Field.item_id` 和 `Comparison.item_id`。

但我检查的这份本地仓库当前仍是 `main`，提交为 `dad8b3f`，比 `origin/main` 落后 10 个提交；本地 `docs/schema/check-task.schema.json` 中还没有 `items`、`Field.item_id`、`Comparison.item_id` 或 `line_no`。因此，不能把“方案已接受”误认为“Schema 已经合入”。拉取到包含增量 PR 的分支后，应重新运行本文的核对。

## 当前正式 Schema 已经覆盖的内容

现有 Schema 能较好表达单品名版本的正式 API 返回：

```text
task_id / status / timestamps / input
documents[]
extractions[].fields[]
comparisons[].values[]
risks[]
summary
errors[]
```

已有的有效约束包括：

- 任务状态区分 `COMPLETED` 和 `PARTIAL`；
- 文件处理失败有显式状态；
- 字段区分 `NOT_IN_DOC`、`MISSING_IN_DOC`、`UNRECOGNIZED`；
- `EXTRACTED`、`LOW_CONFIDENCE` 不能把 `normalized_value` 留空；
- `CONFLICT` 至少有两个值，且严重程度不能是 `INFO`；
- `canonical_value` 必须为 `null`；
- `NOT_CHECKED` 必须有说明；
- 评测未运行时不填假指标。

## 必须在增量 PR 中补齐的内容

### 1. 顶层 `items[]`

建议增加：

```json
"items": {
  "type": "array",
  "items": {"$ref": "#/$defs/Item"}
}
```

建议的 `Item`：

```json
"Item": {
  "type": "object",
  "required": ["item_id", "display_name"],
  "additionalProperties": false,
  "properties": {
    "item_id": {"type": "string", "pattern": "^item_[A-Za-z0-9_-]+$"},
    "display_name": {"type": "string"},
    "description": {"type": ["string", "null"]},
    "line_no": {"type": ["integer", "null"], "minimum": 1}
  }
}
```

`item_id` 的唯一性不能只靠 JSON Schema 的 `uniqueItems`，因为 `uniqueItems` 比较的是整个对象。应在 `validate.mjs` 中检查同一任务内的 `item_id` 不重复。

### 2. `Field.item_id` 和 `Field.line_no`

```json
"item_id": {"type": ["string", "null"]},
"line_no": {"type": ["integer", "null"], "minimum": 1}
```

商品级字段关联商品；整票字段使用 `null`。第一轮不要强制所有字段必须有关联商品，因为发票号、装运日期、整票毛重等字段可以合法地是整票级。

### 3. `Comparison.item_id`

```json
"item_id": {"type": ["string", "null"]}
```

比较对象的身份应由 `item_id + field_key` 表示。整票字段比较时 `item_id` 为 `null`。

### 4. `ComparisonValue.line_no`

建议给每个来源值增加：

```json
"line_no": {"type": ["integer", "null"], "minimum": 1}
```

这样前端可以定位“某一份文件中的哪一行”产生了这个值。`ComparisonValue.item_id` 可以不重复返回，因为父级 `Comparison.item_id` 已经确定商品；若团队重视可追溯性，也可以保留，但必须避免前后端重复含义不一致。

## 当前 Schema 的语义缺口

### 1. 无法区分“部分缺失”和“全部缺失”

现有 `ComparisonStatus` 只有 `MISSING_IN_SOME`。第一版建议保留这个枚举，用 `note` 明确：

```text
所有适用来源均未抽取到该字段
```

不要现在新增 `ALL_MISSING`，除非前端确实需要单独展示。新增状态会影响前端、统计和测试。

### 2. 无法单独表示“部分不可识别”

一个文件可读、另一个文件不可读时，现有枚举没有专门状态。建议暂时返回：

```text
status: NOT_CHECKED
note: 有可用证据，但至少一个适用来源无法识别
```

只有所有适用来源都是 `UNRECOGNIZED` 时，才使用 `UNRECOGNIZED`。

### 3. 低置信度只有字段级信号

`LOW_CONFIDENCE` 目前只存在于 `Field.status` 和 `ComparisonValue.field_status`。第一版可继续让 comparison 按归一值判定 `MATCH` 或 `CONFLICT`，并在 `note` 或 `risks` 中提示人工复核。

### 4. 没有显式 scope 字段

当前用 `item_id: null` 表示整票字段，已经足够支持第一版。暂时不建议增加 `scope`，避免重复表达。若后续必须区分商品级、整票级和文件元数据，再增加：

```text
ITEM / SHIPMENT / DOCUMENT
```

## 不能只靠 Schema 解决的规则

以下约束应放入 `validate.mjs`、数据库或后端业务校验：

- `items[].item_id` 在同一任务内唯一；
- `Field.item_id` 必须引用当前任务的 `items[]`；
- `Comparison.item_id` 必须引用当前任务的 `items[]`；
- `item_id + field_key` 不应产生重复 comparison；
- `summary` 数字与数组实际数量一致；
- `CONFLICT` 的归一值确实不同；
- `2400` 和 `2400.0` 应按同一数值比较；
- 单证类型决定字段是 `NOT_IN_DOC` 还是 `MISSING_IN_DOC`；
- 同一商品在不同文件中的 `line_no` 可以不同；
- 整票毛重不能复制到每个商品。

## 生成器与正式 API 的边界

`data/generator.py` 输出的是内部测试格式：

```text
case_id
task
items
documents
expected.comparisons
expected.risks
```

它不是正式的 `GET /api/v1/checks/{task_id}` 返回体，不能直接用当前 API Schema 校验。正式 fixture 必须组装成：

```text
task_id
status
created_at
finished_at
input
documents
items
extractions
comparisons
risks
summary
errors
```

建议保留两套格式：生成器用于产生源数据和独立 golden 断言，`docs/fixtures/` 用于验证正式接口契约。

## 建议的修改顺序

1. 确认包含 `items[]` 的增量 PR 已合入目标分支。
2. 修改 `docs/schema/check-task.schema.json`：增加 `Item`、顶层 `items`、`Field.item_id`、`Field.line_no`、`Comparison.item_id`。
3. 同步修改 `docs/数据契约.md`。
4. 给单品名正式 fixture 增加单元素 `items[]` 和字段级 `item_id`。
5. 增加一个多品名正式 fixture，覆盖一致、冲突和不同文件行序。
6. 在 `validate.mjs` 增加 ID 引用、唯一性和重复 comparison 检查。
7. 执行 `npm install` 和 `npm run validate`。
8. 联调后再评估是否新增 `ALL_MISSING`、`PARTIAL_UNRECOGNIZED` 或 scope 枚举。

## 推荐的第一轮方案

立即加入：

```text
items[]
Item
Field.item_id
Field.line_no
Comparison.item_id
ComparisonValue.line_no
```

暂时不加入：

```text
ALL_MISSING
PARTIAL_UNRECOGNIZED
scope
```

这些状态和字段等真实联调暴露需求后再增加。这样可以落实已经被 D 接受的 `items[]` 方案，同时保持现有前端状态枚举兼容。
