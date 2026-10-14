# JSON Schema 校验说明

[`docs/数据契约.md`](../数据契约.md) 与 [`docs/report-content-api.md`](../report-content-api.md) 描述接口的业务语义，本目录下的 JSON Schema 文件定义机器可校验的严格响应结构。

---

## Schema 文件清单

| 文件 | 校验对象 |
|---|---|
| [`check-task.schema.json`](check-task.schema.json) | 检查任务状态与结果（`POST /api/v1/checks`、`GET /api/v1/checks/{task_id}`） |
| [`report-content.schema.json`](report-content.schema.json) | 结构化报告内容视图 v2（`GET /api/v1/checks/{task_id}/report?format=json&view=content`） |
| [`evaluation.schema.json`](evaluation.schema.json) | 系统评测摘要与批次列表（`GET /api/v1/evaluation/latest`、`GET /api/v1/evaluation/runs`） |
| [`validate.mjs`](validate.mjs) | 契约示例数据与 `summary` 计数自洽性校验脚本 |

---

## 运行校验

在仓库根目录执行：

```sh
npm ci
npm run validate

# 校验后端脚本实际生成的任务与评测输出目录
node backend/tools/validate_outputs.mjs backend/.out
node backend/tools/validate_reports.mjs
```

---

## 核心结构与语义约束

| 约束项 | 校验规则 |
|---|---|
| `additionalProperties: false` | 拒绝任何未在契约中声明的额外字段 |
| `canonical_value` 恒为 `null` | Schema 强制约束，系统不裁定哪份单证正确 |
| `CONFLICT` 条目约束 | 至少包含 2 条 `values`，且 `severity` 必须为 `WARNING` 或 `ERROR` |
| `SINGLE_SOURCE` 条目约束 | `values` 数组长度严格限制为 1 |
| 字段状态与 `normalized_value` 联动 | `EXTRACTED` / `LOW_CONFIDENCE` 的 `normalized_value` 必须非空；`NOT_IN_DOC` / `MISSING_IN_DOC` / `UNRECOGNIZED` 必须为 `null` |
| 评测状态与 `metrics` 联动 | 非 `DONE` 状态的评测结果 `metrics` 必须为 `null`；`DONE` 状态下校验 `counts` 与 `metrics` 的换算一致性 |
| `summary` 计数自洽性 | `validate.mjs` 与 `validate_outputs.mjs` 交叉核对 `summary` 各项计数与实际数组长度完全相等 |
