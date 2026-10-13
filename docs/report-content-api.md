# 结构化报告接口 v2（#51，F → D）

基于主线 `04307d1` 的后端整改。默认复用已有报告端点，不另建报告数据源；报告展示、HTML/CSS、布局和打印由前端负责。报告只投影已保存结果，不重新 OCR、不重新运行比较、不用当前规则覆盖原判断。

## 请求与迁移

`GET /api/v1/checks/{task_id}/report?format=json&view=content`

`format=json`、`view=content` 均为默认值。响应为 JSON 附件，`nosniff`、`no-store`；顶层 `report_version="2"`。适用于 COMPLETED、PARTIAL、FAILED，正在处理返回 409/TASK_NOT_FINISHED，不存在返回 404/TASK_NOT_FOUND。

显式完整归档：`GET /api/v1/checks/{task_id}/report?format=json&view=archive`。保留完整内部抽取结构、原始字段值和审计 before/after；不附全局来源目录或模型运维记录。旧任务中的底层错误文案也转为用户原因；数据库不修改，`result_hash` 仍是已保存原结果的 hash，不能用投影响应重新计算它。原件字节仍通过文件下载接口取得。

`format=html` 返回 **410/REPORT_PRESENTATION_MOVED**，明确建议使用前端报告页面打印/导出；其他格式/视图返回 400/INVALID_REPORT_FORMAT。D 需将旧 HTML 下载按钮接到前端呈现流程，JSON 下载请求保持有效。仅本后端 PR 通过不表示 D 的 HTML 迁移或联合验收已完成。

## 默认内容及关联

| 字段 | 含义/关联 |
|---|---|
| report_version / view / generated_at / result_hash | 契约版本、投影视图、导出时间、原结果标识 |
| task | task_id/status/时间/input/summary；不嵌套重复的全部结果 |
| documents | 原文件清单与逐文件状态；identifiers 保留 document_no/invoice_no 各自证据；original_url 为同源下载路径 |
| items | 原 item_id、label、alignment_status/basis/note 和成员 file_id/item_no；以 label 展示，不把 ID 当品名 |
| comparisons | 原 comparison_id、scope/item_id、field_key/label、status/severity/note/unit/values；枚举不变，D 统一翻译 |
| comparisons[].values[].evidence | 唯一同文件、同字段、同商品成员的 raw_text、bbox_unit、line_no；无法唯一定位 status=UNAVAILABLE，值为 null，不猜首条或跨行取证；原值/页/bbox 仍在 value 中 |
| unaligned_evidence | 未归组商品行的原文与字段，按 file_id/item_no 定位，不能当作整票证据 |
| risks | 原风险级别和关联 ID、业务 title/detail/source；固定的重复未核实前后缀拆为 rule_context |
| errors | 原非规则重复告警与错误码、level/file_ids；解析错误为受控用户原因，失败页码保留。运维配置/异常进入服务端日志 |
| corrections | 完整审计链、原因、操作者核实状态与变更身份；默认 before/after 保留有效值/unit/status；原始完整字段证据在 archive |
| provenance | 历史规则版本语义、本票关联的当前来源状态及核实状态 |
| limitations | 固定语义代码，由 D 统一组织说明，不是通过标志 |

file_id、item_id、comparison_id、risk_id 和原枚举保持稳定。`SINGLE_SOURCE`、`NOT_CHECKED`、失败、未核实仍必须独立显示；`COMPLETED` 仅表示处理终态。各 summary 检查计数和比较/风险结论来自原任务，不因报告投影而重算。

## 历史与来源语义

- `execution_rule_version=null` / `execution_version_status=UNKNOWN`：原任务没有历史版本记录，不用当前版本补齐。
- 派生任务使用最后修订审计中的 `rule_version`，状态 RECORDED_IN_CORRECTION；审计链保留各次版本。
- `source_metadata_scope=CURRENT_AT_EXPORT`：关联定义与监测状态是导出时当前信息。risk.rule_context.definition_scope 同样明确；不能用它证明当时读取了这些来源或当时完成法律适用核验。
- 仅按该票风险 rule_id 的当前定义关联 source_ids。没有可匹配定义时空列表/UNKNOWN，不附全部国家规则和全套目录。
- `verification_status=UNVERIFIED/NOT_CHECKED/UNKNOWN` 均不是 VERIFIED。未核实公共警告合并到 provenance.rule_verification_status，风险仍保留逐项核实状态，不以少一条重复 error 当作已通过。
- `/api/v1/rules/sources` 是独立业务来源查询，采用允许字段列表。抓取尝试、缓存头、快照路径、原始异常与操作参数仍在受限运行文件中，不进公共响应。来源成功抓取不是法律适用已核实。

## 响应样例与验证

[默认修订报告样例](fixtures/report/content.json) · [JSON Schema](schema/report-content.schema.json)

```sh
node backend/tools/validate_reports.mjs
python backend/tools/test_workflow.py
python backend/tools/test_rule_monitor.py
python backend/tools/accept_workflow.py
```

契约测试纳入 CI，包含归档/默认分离、未知历史、关联来源、运维信息投影、失败范围与旧 HTML 迁移。没有改变 CheckTask 契约或原比较算法；没有扩展 EDI 支持。
