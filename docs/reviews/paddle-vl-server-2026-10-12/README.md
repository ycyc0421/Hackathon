# F 固定候选：服务器与 PaddleOCR-VL 验收

验收时间：2026-10-12 至 2026-10-13（北京时间）。[实际服务器入口](https://hackathon.ychome.net/?mock=0) · [PR #37](https://github.com/ycyc0421/Hackathon/pull/37)。

## 下载与版本

[完整结果与复现脚本 ZIP](server-delivery-evidence.zip)，2,455,258 字节。

SHA-256：`d74bd4e868ddcd6fae1cb27d4fbd6640b2310e3773ba2b46ba1d85b312d4acad`。

- 正式服务器运行代码：`831e90f5b7c98f7f39ba86e52161fd75cc8564e2`，`/health.release_revision` 可核对。
- 隔离完整材料回归代码：`333a71140ac2728ef476d5ecc3a7708d0b3dd98f`；随后新增健康版本标识、回退配置备份与旧测试预期修复，正式原件重新验收。
- 已合并 main `d223d7cfe94acccc60b96656f2f93f866b63e087`，包含 #39/#42/#44。文档和探针等待期限的最终提交另见 PR head，不冒充被测运行版本。
- 原件及金标复用 B [完整独立材料](https://github.com/ycyc0421/Hackathon/raw/e2976003e68a8f17208ee1e2fac6f46a8c7424ca/docs/reviews/backend-independent-fca14f5-2026-10-12/review37-fca14f5-independent.zip)，SHA-256 `04d959ba3f986824ccc43a18611ef8004cd86bd9e2d23583683183ebe48e258c`。本包不重复打包原件，不改变原始字节或预期。

## 真实结果

| 目录 | 结果 | 范围 |
|---|---|---|
| digital | 125 票 / 329 文件，8053 项检查通过 | 100 票文本 PDF、JSON 缺数量、23 EDI 失败路径及混合输入；实际 TCP HTTP，含请求、公开返回、报告和输入哈希 |
| extra-final | SG/AU 126 字段、扫描 30 项通过 | 原文国别核对；SHP-00001 三张 PNG 调用新 VL 推理，耗时约 275 秒 |
| final-server-acceptance | 93 项通过，84.03 秒 | 隔离环境三份 T 恤原始 PDF，热启动新 VL 推理 |
| production-preflight | 93 项通过，342.58 秒 | 正式发布三份 T 恤冷启动预检，内存中的测试 API 调用真实模型服务；不是公网上传 |
| restart-final | 21 项通过 | 四票活动/排队任务，每票三份原件；第五票 429；实际 SIGKILL API 后重启，12 份原件保留且文件状态结束 |
| production-final | 41 项通过；编号修订另 6 项通过 | 公网文本样例、前端静态资源、三份原始 PDF 上传、主体/数值/来源、原件字节、报告导出、修订重算/幂等；实际重启正式 API 后两份任务完全一致；document_no 修订不改原任务或原件 |
| model-outputs | 实际原始模型 JSON | 六份隔离扫描与三份正式 T 恤原件输出；保留页、区域与 HTML 网格；未用保存输出替代新推理 |
| runtime.json | 三正式服务 active | 固定模型清单、真实发布目录、总内存上限与峰值；不含密钥、共享配置或运行数据库 |

三正式服务共用 slice MemoryMax=8,589,934,592，最终 MemoryPeak=4,449,091,584 字节，约 **4.14 GiB**。该峰值覆盖本轮记录，不能当所有版式的上界或容量 SLA。单模型并发，最多接纳四票；长任务必须按 task_id 查询，不因前端等待而重复上传。

## 如何核验

解压后从仓库根目录运行：

```sh
node backend/tools/validate_outputs.mjs <解压目录>/digital/public
```

该目录 **126 份**实际返回通过 Schema、引用与计数一致性检查（125 上传任务加修订任务）。`replay/` 保留本轮真实请求脚本；路径常量和隔离服务器配置需按本机设置。`accept-production.py` 会实际重启 API，`accept_server_restart.py` 会中断指定隔离服务，不能直接当作无副作用的日常探针运行。不可执行旧根因脚本并把旧失败仍存在当作修复通过。

## 未计为通过的事项

- digital 的 6569 项字段直接对照仍有 **753 项品名 normalized_value 字符串差异**，保留在 field-checks.json；B 已确认涉及中英词表/同格 SKU 口径，不能宣称所有字段完全一致。
- 23 EDI 均为明确 UNSUPPORTED/FAILED，混合输入 PARTIAL；不代表 EDIFACT 成功解析。C 的首批解析器、F 后续接入、D/B E1 联调仍按 #40 推进。
- 10 票地址差异无提取/比较；PI 为现有 OTHER；包装种类没有证据时 unit=null，不能默认箱数。
- 未开展候选完整浏览器人工验收、D #43 私有 B1–B6 输入、模型微调、全模板准确率或法规适用验收。B 对旧 main 的浏览器 30 项不能挪作本候选的浏览器结果。

实现与运维入口见 [F 交付说明](../../PADDLE_VL_DELIVERY.md)。B/D 可按这组固定输入和版本独立复验，不以 COMPLETED、0 冲突、CI 或可访问代替业务结论。

## 发布脱敏

公开证据包已将部署 IP、部署账户主目录和本地用户路径替换为占位符。字段值、检查结果及原件哈希保留；路径字符串不再代表实际机器位置。历史服务器运行 revision 仅用于区分原始验收环境，本 PR 历史已整理为脱敏的单一交付提交。
