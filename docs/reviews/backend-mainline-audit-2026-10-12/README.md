# F 后端主线核查与修复

2026-10-12，基于候选分支 `07306e9` 继续修复。核查了 234 个受控文件的目录、后端主要模块、数据与部署入口，以及开放 issues #38、#40、历史 #3/#4 和开放 PR #37/#39/#41。此记录区分候选实现、接口验证和生产部署。

## 本轮完成

1. 人工修正保留尚未完成的 OCR 品名核验。修改币种等其他字段后，品名继续 NOT_CHECKED；只有明确人工修正对应品名才解除该条限制，原任务和原文证据保持可追溯。
2. 修正后的内部数值警告重新计算，涵盖 quantity × unit_price 与 gross < net。人工修正值参与检查，已解决的旧警告移除，新问题仍会产生警告。
3. 多模态 PDF 兜底逐页转写并保存页边界；页数不一致或某页失败显式失败。文本 PDF 票级字段在唯一页面有同值证据时补页码，跨页重复或无法唯一定位继续为 null。逐页模型请求增加请求次数，本轮验证为受控响应，未重跑外部模型。
4. 更新历史能力文档：SQLite 已合并 main；人工修正与报告接口已在 #37 实现，不能继续记为未实现，也不能据此宣称生产已经部署。

## 验证与证据

- `backend/tools/test_workflow.py`：11 项，10 通过，1 个 Windows HTTP 用例跳过；真实 HTTP 另行验证。
- `backend/tools/test_reader_pages.py`：4 项通过，已纳入 CI。
- 审查、Paddle 适配和 JSON 回归通过；Windows 跳过项不作为通过计数。
- `backend/tools/accept_workflow.py`：14 项真实 HTTP/SQLite 工作流验收通过，包括修正、幂等、旧哈希拒绝、报告导出和重启读取。
- 隔离 HTTP 回归：T 恤保存输出修改币种后保持品名 NOT_CHECKED；逐份人工确认后 MATCH；SHP-00015 修正金额后旧金额警告清除；受控两页 PDF 实际上传后，单据号 page=1、总额 page=2、重复币种 page=null，行数量分别 page=1/2。
- 5 份公开接口返回通过当前 Schema 和关联/计数一致性校验。

[下载接口证据与回放脚本](http-regression-evidence.zip)。包内含 5 份公开返回、14 项验收记录和脚本。脚本读取前轮 `.out/shirt/http-result.json` 与 `.out/followup-fixed/SHP-00015.json` 保存输出；输入来源见[前轮原件回归记录](../backend-followup-fixes-2026-10-12/README.md)。这些是保存输出的修正回归及受控 PDF 上传，不是本轮重新 OCR，也不是 100 票完整评测。

## 剩余主线与职责

| 顺序 | 事项 | 下一步与完成依据 |
|---|---|---|
| 1 | [PR #37](https://github.com/ycyc0421/Hackathon/pull/37) 集成交付 | B/D 验收修复接口与展示，合并后检查部署和公网原件请求；候选 CI 不能替代部署验收 |
| 2 | [PR #39](https://github.com/ycyc0421/Hackathon/pull/39) 数据关联 | C 侧关联补全合并后，F 验证迁移、重启读取及商品/证据关联，不重复实现另一套迁移 |
| 3 | [#40](https://github.com/ycyc0421/Hackathon/issues/40) EDI | C 提供解析器，F 接入真实 EDIFACT；D 核验上传与展示。[#41](https://github.com/ycyc0421/Hackathon/pull/41) 模拟响应不是解析通过证据，现有 JSON 通道不是 EDIFACT 支持 |
| 4 | [#38](https://github.com/ycyc0421/Hackathon/issues/38) 覆盖补齐 | 地址字段与 PI 类型先统一 C/D 契约；取得完整 100 票及 4 行空 HS 原件后跑完整 HTTP 回归。已取得材料中的 9 组最小原件不替代完整集 |
| 5 | 正式金标与评测 | 固定许可、字段预期和分母后运行，保留错例；尚未运行继续 NOT_RUN |

正式规则来源与资源容量仍需验收；本轮不扩展规则或重写队列。优先把候选修复合并、联调、部署和原件验收完成。

## 20:00 补充：F 可独立交付项

- 新增 `GET /api/v1/capabilities`，返回部署实例的格式与上传限制，明确区分项目 JSON 与尚不支持的 EDIFACT/X12；OCR 开关按运行配置声明，不冒充模型健康检查。
- 新增 `GET /api/v1/checks/{task_id}/files/{file_id}`，下载保存的原始字节。全部失败的 EDI 任务仍可下载，派生任务沿审计链找到最初原件；文件缺失明确 404，不重建。4 项真实 HTTP 回归通过，纳入 CI。
- 对本地已获取的 C 分支 `0f32b411548a3bcd6459ca71bcccc32d84c7dc26` 做隔离组合验证：保留 F 的审计/派生方法，应用 C 的 data 文件与初始化 backfill 调用。数据层 23 项、存储 10 项、工作流 14 项、原件接口 4 项通过。该组合未合并到业务分支；F 的存储测试夹具补上真实商品行，使 members 不再指向不存在的行。
- 部署准备只读检查：公开 `/health` 返回 ok/version=0.1.0，但没有提交号，不能确定实际生产版本；新服务器 BatchMode SSH 返回 Permission denied(publickey,password)，当前会话无可用登录身份。未切换生产或重启服务。
- Git fetch 两次失败（连接重置/空响应）；#38/#40 网页可读取，最新 #40 尚无 C 解析器交付回复。组合验证只对应上述固定 C 提交，不声称覆盖尚未取得的新提交。

F 报文边界已在 [#40](https://github.com/ycyc0421/Hackathon/issues/40#issuecomment-6123316495) 回填。剩余交付条件：C 解析器与确认契约、B 完整原件、D 真实前端验收、PR 集成和可用部署登录/发布环境。这些条件满足后继续接入与部署验收；不能据本轮接口修复宣称全项目完工。

## B 新材料与 D 新通知的跟进

B 已在 #44 发布完整 EDI 包（固定 `9b2896d68af4f2a20640efc0a762a4903806104d`）；下载 ZIP 的 SHA-256 已核对为 `5502ee4c277fb16f71ced188886e09e10b707078c869017fe588e99350c5565c`，此前“B 完整 EDI 材料未交付”的依赖已解除。23 份原件实际 multipart 上传、GET 查询与下载字节验证完成；每份仍 UNSUPPORTED/FAILED，全部公开返回通过 Schema 与一致性校验。**这是失败语义和来源验证通过，解析验收仍 BLOCKED，不能算 23 份解析通过。** [完整接口结果与脚本](edi-current-http.zip)。脚本需要将 B ZIP 解压至 `backend/.out/edi-bundle`。

D 的 #43 已交付编号展示、工作流请求和整票证据定位候选。F 同时修复公开投影删除未对齐行的缺口：这些行保留 raw_text/raw_value/page/line_no，item_id=null，不冒充整票字段；新增回归加入 CI。D 的 B1–B6 详细复现交付位于其未入库的私有说明，公开 PR 只列出名称；需取得完整输入、请求和预期后逐项判定，不能宣称全部已修复。C 的标准报文解析器仍未在已获取开放 PR 中交付。
