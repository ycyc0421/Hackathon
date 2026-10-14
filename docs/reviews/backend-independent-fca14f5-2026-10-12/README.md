# PR #37 固定版本独立复验

关联：[#38](https://github.com/ycyc0421/Hackathon/issues/38)、[#40](https://github.com/ycyc0421/Hackathon/issues/40)、[PR #37](https://github.com/ycyc0421/Hackathon/pull/37)。

**被测源码固定为 `fca14f56910333c4bac8c72cfd6428ffe2fb6f2a`。核心提取和比较修复已取得独立原件证据；目的国归一、处理中原件持久化/终态清单、包装单位语义仍需处理，不判定业务整体验收通过。**

本目录仅发布验证材料，没有修改应用、原件或部署。此材料分支基于 main，不能将其分支 HEAD 当成被测后端版本。

## 获取及复现

- [完整证据 ZIP：原件、独立预期、请求/返回、报告、原始 OCR 输出及脚本](review37-fca14f5-independent.zip)（7,055,840 字节）。
- [独立复验记录](复验记录.txt)、[复现方法及路径限制](复现方法.txt)。
- [公开输出 Schema/关联/计数验证日志](schema-validation-all.log)、[135 份公开返回索引](validation-index.json)。
- [Python 3.12 OCR 环境锁](requirements-py312-ocr.lock.txt)、[Python 3.13 诊断环境锁](requirements-py313-ocr.lock.txt)。

ZIP SHA-256：`04d959ba3f986824ccc43a18611ef8004cd86bd9e2d23583683183ebe48e258c`。ZIP 已重新打开、检查 CRC 与成员哈希，原件测试前后字节一致；包内不含模型、运行数据库、凭据或生产日志。

原件范围为 300 份文本 PDF、3 张模拟扫描 PNG、3 份用户提供的 T 恤 PDF、23 份 EDI、2 份项目 JSON，共 331 份不同原件。包内含完整 100 票文本原件及四行空 HS 反例；不是原数据集 360 份衍生输入全量包。合成模板回归与 T 恤 DEMO 单证不代表真实跨版式泛化或法律合规。

主驱动 `review_latest.py` 接收固定源码、数据包及输出目录参数，只启动 loopback 服务并使用独立 SQLite/上传目录。部分补充脚本仍有本轮 Windows 路径常量，跨机复跑须按复现说明调整；中断恢复的新复验需要实际中断的任务与运行库，不能以保存返回代替。

## 已完成的独立检查

| 范围 | 已验证事实 |
|---|---|
| 100 票、300 文本 PDF | 全部实际上传并 EXTRACTED；商品行数正确；5,816 项核心字段值、300 项自身编号、3,461 项单位关联检查通过 |
| 跨文件与内部数值 | 40 项数量/HS/金额真实冲突、20 项干净/无害格式无误报检查通过；20 项内部金额/重量警告命中；实际修正后旧警告清除 |
| 四行空 HS | SHP-00007、SHP-00097 均保留四行，首行 HS 明确 MISSING_IN_DOC，后续数量与金额未错列 |
| 新 OCR | Python 3.12.13 / Paddle 3.2.0 / PaddleOCR 3.7.0 / PaddleX 3.7.2 默认配置，两组共六份原件实际推理与 TCP HTTP 完成；未禁用 oneDNN，未使用外部 LLM 或保存输出替代 |
| T 恤 | 数量 500；PI/CI 单价 2.80、金额 USD 1400；PL 商品行包装数 20、净重 150、毛重 170、体积 1.68；票/行金额 NOT_IN_DOC，未生成 USD 500 或零；包装单位另待确认 |
| 不确定性与修正 | 品名保持 NOT_CHECKED；改币种不清除品名待核验，两次派生后原件字节仍一致；金额单位与币种同步，原始证据保留 |
| 已完成结果重启 | 完成、派生及 PARTIAL 任务结果可重读，派生原件仍可下载；不是生产重启验收或自动续跑证明 |
| EDI | 23 份真实上传均 UNSUPPORTED/FAILED，混合 PDF+EDI 为 PARTIAL，原件下载字节一致；不计为 EDI 解析/语法验收 |

## 未完成与职责

| 事项 | 事实与定位 | 对接 |
|---|---|---|
| 原件目的国归一 | 42 票、126 份 Singapore/Australia 原文字段 NORMALIZE_FAILED；COUNTRY_GLOSSARY 缺少 SG/AU 名称和代码，而请求与 CODE_TO_NAME 接受它们。失败在归一化，不是原件缺值 | F 修复，C 确认一般国别语义，B 回归，D 展示归一失败 |
| 处理中原件及清单 | 三份已提交文件在中断后仅首份落盘；重启为 FAILED/TASK_INTERRUPTED，但首文件仍 PARSING，其余两个文件下载 404。main 先读内存，runner 在逐文件解析循环里才落盘；重启收尾未更新逐文件状态 | F 处理持久化/收尾；D 确认失败展示；B 复验。无需把自动续跑作为本次修复前提 |
| 包装单位 | T 恤 PL 原文 PKGS、裸数 20，返回 packages.unit=CARTON；人工金标 unit=null。20 的数值已验证，原件未证明“20 箱” | C/F 明确单位约定与来源，D 按一致语义展示 |
| EDI 解析 | 当前被测版不支持 EDIFACT/X12；首批 INVOIC D:96A:UN / 单 UNH / ASCII 或严格 UTF-8 待 C/F 确认与交付 | C 解析器，F 流程/映射/错误，D 前端，B 最终联调 |

描述 normalized_value 与金标直接比较的 753 处差异已核对为中英词表及同格显式 SKU 口径差异；raw_value 的 753 项业务描述均完整。原始严格对照保留，不把它们计为 753 处确认漏读，也不修改金标强行通过。

Python 3.13 / Paddle 3.3.1 默认配置的六份扫描件有 oneDNN 错误；关闭 oneDNN 的 TCP 尝试连接中断、TestClient 尝试 300 秒未获终态。这些记录保留，不计解析成功，不据此断言 Linux 生产崩溃；不能与 Python 3.12 成功结果混成一个运行环境的成功率。

地址比较、PI 类型/必填契约、#43 私有 B1–B6 反例、#39 组合迁移、浏览器、线上部署/重启及正式规则适用仍未验收。COMPLETED、0 冲突、135 份 Schema 检查通过或 25 项相关回归通过均不等于业务或法律验收。
