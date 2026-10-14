# 结构化报告接口说明（ReportContent v2）

报告接口将已完成的检查任务投影为结构化报告视图（`view=content`）或完整归档视图（`view=archive`）。报告的排版、HTML/CSS 渲染与打印样式由前端 `web/src/report/document.js` 负责生成，后端不直接拼接 HTML。

JSON Schema 定义见 [`docs/schema/report-content.schema.json`](schema/report-content.schema.json)，响应示例见 [`docs/fixtures/report/content.json`](fixtures/report/content.json)。

---

## 1. 接口端点与视图模式

| 请求路径 | 视图说明 |
|---|---|
| `GET /api/v1/checks/{task_id}/report?format=json&view=content` | **默认报告内容视图**（`report_version="2"`）：返回用于生成正式报告的结构化内容，前端据此渲染自包含 HTML 文档 |
| `GET /api/v1/checks/{task_id}/report?format=json&view=archive` | **完整证据与审计归档视图**：保留完整内部抽取结构、原始字段值及人工修正前后的完整证据快照，供离线留档与核查 |

- **适用状态**：`COMPLETED`、`PARTIAL`、`FAILED` 终态任务均可导出；任务仍在处理中时返回 `409 TASK_NOT_FINISHED`，任务不存在返回 `404 TASK_NOT_FOUND`。
- **旧版 HTML 参数响应**：请求 `format=html` 返回 `410 REPORT_PRESENTATION_MOVED`，引导使用前端自包含 HTML 导出与浏览器打印。

---

## 2. `view=content` 核心字段结构

| 字段路径 | 语义与展示规范 |
|---|---|
| `report_version` / `view` / `generated_at` / `result_hash` | 契约版本（`"2"`）、视图类型、报告生成时间及原始结果 SHA-256 指纹 |
| `task` | 任务元信息（`task_id`、`status`、`created_at`、`finished_at`、`input`、`summary`） |
| `documents[]` | 上传文件清单、处理状态、自身单据编号（`identifiers`）及该文件独有但未参与跨文件比对的补充业务字段（`fields`，如收发货人、集装箱号、起运港/目的港） |
| `items[]` | 多品名行组目录（`item_id`、展示名 `label`、对齐状态 `alignment_status`、对齐依据 `alignment_basis` 及各文件内的成员行号 `members[]`） |
| `comparisons[]` | 跨文件比对结论；每个取值项附带唯一匹配的原文证据 `values[].evidence`（含 `status: "LOCATED" \| "UNAVAILABLE"` 与 `raw_text`） |
| `unaligned_evidence[]` | 未能跨文件归组的单文件商品行证据，仅作为单文件记录展示，不混入整票比对结论 |
| `risks[]` | 合规与归类风险提示；规则核实状态、关联来源 ID 与适用条件统一收口于 `rule_context` |
| `corrections[]` | 人工修正审计链，记录每次修正的时间、原因、源任务/派生任务 ID 及有效值前后变化（`before` / `after`） |
| `provenance` | 规则版本与官方来源追溯信息（执行时规则版本、当前定义版本、关联来源目录与监测状态） |
| `limitations[]` | 报告使用限制的语义代码列表（由前端统一译为中文说明） |

---

## 3. 关键呈现与降级约束

1. **严禁将未知或未校验状态呈现为通过**：
   - `SINGLE_SOURCE`（仅一份文件提供）与 `MATCH`（多份文件一致）在报告中分块展示；
   - `PARTIAL`（部分完成）与 `FAILED`（检查失败）任务不展示绿色的“无待处理项”确认条。
2. **禁止泄露内部机器标识**：
   - 单证类型、比对状态、行组对齐状态、来源监测状态及适用条件均通过 `web/src/api/labels.js` 转为规范中文，正文中不直接暴露 `COMMERCIAL_INVOICE`、`item_001` 或内部布尔键名。
3. **历史版本如实追溯**：
   - 原任务未记录执行时规则版本（`execution_rule_version = null`）时，报告如实标注「未记录」，绝不用导出时刻的 `current_definition_version` 回填冒充。

---

## 4. 校验命令

```sh
node backend/tools/validate_reports.mjs
node --test tests/report-document.test.mjs
python -m pytest backend/tests/test_workflow.py
```
