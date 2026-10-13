# 人工修正、报告与规则库第一版

## 人工修正

后端提供人工修正接口，报告页入口由独立前端 PR #43 接入。仅修改已抽取文件中已有的票级/商品行字段，禁止增删商品行、改判定、改原始证据。原因必填，操作者记录为 anonymous（当前无身份认证）。修正生成新任务，重新运行对齐、比对和规则；原任务及 raw_text/raw_value/坐标完整保留。不重新执行 OCR。

- `GET /api/v1/checks/{id}/corrections` 返回结果哈希和审计。
- `POST /api/v1/checks/{id}/corrections` 接受 `request_id`、`source_hash`、`reason`、`changes`；每项 `file_id`、可选 `item_no`、`field_key`、字符串 `value`。
- 过期哈希 409，同 request_id 同内容幂等，变更内容冲突 409；非法批次全部回滚。修正结果与审计在 SQLite 同一事务保存。

## 报告

`GET /api/v1/checks/{id}/report?format=json&view=content` 提供结构化报告；`view=archive` 显式下载完整抽取及审计归档。后端 HTML 已移至前端呈现，旧 format=html 返回 410/REPORT_PRESENTATION_MOVED。详见 [报告 v2 契约与迁移](report-content-api.md)。终态失败和部分完成也可导出，处理中返回 409。结果、失败范围、未检查项、OCR 校正、人工修正和规则来源均保留；COMPLETED 不等于合规通过。

## 项目交换输入

第一版是 **hackathon-trade-json-v1**，不是标准 UN/EDIFACT 或 X12。上传 `.json`，UTF-8、最大 1 MiB、最多 200 行；一份文件对应发票、装箱单或提单。字段名使用现有 field_key，原始值必须为字符串；度量值应明确带单位。金额币种在票级 currency 给出。重复键、重复行号、未知字段显式失败。标准 `.edi/.x12` 仍不支持。

### 实际格式能力与原件下载（F 候选分支）

`GET /api/v1/capabilities` 返回版本、上传限制、格式扩展名与 supported。PDF 文本层可用，扫描 OCR 的 `scan_ocr_configured` 以及 IMAGE 的 supported 按当前 OCR/模型配置返回；配置就绪不代表模型健康或准确率验收。项目 JSON 单独声明格式，UN/EDIFACT 和 X12 明确 supported=false，`.txt` 不作为 EDI，扩展名匹配不区分大小写。D 可用该接口展示部署实例的实际范围。

`GET /api/v1/checks/{task_id}/files/{file_id}` 以附件下载保留的原始字节，文件编号来自 documents[]。支持 FAILED/PARTIAL 任务，无需存在比较卡片；多次人工修正后的任务沿审计链下载最初原件。不存在文件返回 `404 FILE_NOT_FOUND`，原件保存失败或已移除返回 `404 SOURCE_NOT_AVAILABLE`，不从抽取值重建文件。响应为 application/octet-stream，附 attachment、nosniff 和 no-store；EDI 原文展示可由 D 对下载字节解码，不能当作 HTML 执行。

上述接口沿用当前匿名任务访问方式。接口实现和测试通过不表示前端已接入或生产已部署。F 报文职责与 C 待确认契约见 [#40 回复](https://github.com/ycyc0421/Hackathon/issues/40#issuecomment-6123316495)。真实 EDIFACT 仍需 C 解析器和原件回归。

```json
{
  "format": "hackathon-trade-json-v1",
  "doc_type": "COMMERCIAL_INVOICE",
  "fields": {"invoice_no": "INV-001", "currency": "USD", "gross_weight": "120 KGS"},
  "line_items": [{"item_no": 1, "fields": {"item_code": "A1", "description": "CERAMIC MUG WHITE", "quantity": "100 PCS", "amount": "250.00"}}]
}
```

## 静态规则来源

`backend/app/rules/source_catalog.json` 是官方来源清单。运行 `python backend/tools/crawl_rule_sources.py`，抓取清单、正文快照与复核记录默认写入忽略提交的 `backend/.out/rule-sources/`；部署时通过 `--output` 指定运行目录，并将后端 `RULE_SOURCE_DIR` 设为同一目录。仅访问官方 HTTPS 白名单，限定体积/超时，不绕过站点挑战、不自动发布规则，详见 [动态监测说明](dynamic-rule-monitor.md)。未配置监测时仅返回来源目录，状态为 `NOT_CHECKED`，不提供历史抓取成功记录。

首批来源：欧盟委员会食品接触材料法规概览、EUR-Lex 陶瓷指令、FDA 陶瓷铅污染执法指引、GOV.UK 食品包装概览。正文抓取失败会留痕，不冒充成功。

旧演示规则可从 Git 历史追溯，不再额外保留副本，也不再运行其中无条件原产地证明、全 HS69 食品接触、全 HS85 CE/FCC、陶瓷一律 FDA 事先通知等判断。新规则仅对 6911/6912 提示用途及适用条件待核对；HS 编码不能证明食品用途，未获得用途、测试报告、销售阶段/地区实施信息时不作合规结论。国家税则、贸易方式、优惠原产地、其他商品尚未覆盖。

目的国规则分两类执行：hs_rules 生成“归类待复核”提示，certificate_rules 基于目的国和 HS 前缀生成 OTHER 类型的“支持资料待人工核对”提示。当前数据契约未提供支持文件的识别、适用性和商品对应关系，因此不能凭编码命中断言“可能缺少”或“系统未识别到”；即使上传了 OTHER 类型资料，也不能据此视为已满足要求。任何文件未成功解析（包括仍在排队或解析中）时，提示“无法确认”，不输出缺失结论。提示保留候选规则编号和官方来源，以便报告关联来源监测状态；这不代表规则已经核实。

同一商品、同一编码在多份文件中出现时合并支持资料提示并保留所有文件关联；已归组商品按商品编号区分，未归组行按文件和原始行号区分。单份文件的页头编码与商品行编码重复时，不再额外生成票级支持资料提示。

**抓取成功不等于法规适用核实。** 当前 verified=false，仍显示“演示规则·未经核实”。`rule-source-latest` 或运行时 `RULE_SOURCE_DIR` 只提供来源快照、哈希和变化队列，不会自动替换 `countries.json` 或把规则激活为正式合规依据。核实人员、日期与有效条款须由团队逐条复核后再确认；不会用爬虫或 AI 自动把 verified 改成 true。

此分支依赖 SQLite 接入 PR #33；测试及抓取使用新服务器 <deployment-host> 的独立验证目录，未切换生产版本。

## 验证记录（2026-10-12）

- 新服务器：修正/报告 9 项、交换 JSON 6 项、静态规则 3 项全部通过；其中包含真实 HTTP TestClient 上传与修正。
- SQLite 10 项、数据层 12 项、部署与回退 24 项通过；原有比对、审查边界、OCR adapter、接口与挑战样例通过。
- 前端 49 项逻辑测试、Vite 构建、4 个数据契约样例通过。尚未进行候选版浏览器人工验收或生产整站发布。
- 初次官方来源 3 个成功抓取；EUR-Lex 页面返回验证挑战。后续通过官方 CELLAR 接口补抓陶瓷指令正文（8 页），新增修订进度源，现为 5 个来源全部成功。快照仅作证据，不能替代法律适用及国家实施条款复核。

## 服务器交付更新（2026-10-13）

上述 2026-10-12 早期验证与未部署说明保留为历史记录。当前已同步 main 的多商品回填并发布 PaddleOCR-VL 正式候选，原件持久化、中断状态、修订与部署回退的当前范围见 [F 主模型交付](PADDLE_VL_DELIVERY.md)。规则核实及真实 EDI 解析的边界仍有效。
