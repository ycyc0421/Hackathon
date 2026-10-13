# B 侧增量独立复验（脱敏发布版）

发布版说明：仅脱敏不必要的本机路径及服务器部署标识；原始本地证据保留，131份输入原件逐字节不变，保存响应的业务字段逐结构核对不变。脱敏后报告、ZIP和受影响成员的哈希重新生成，不能与原始ZIP混用。

[下载B侧完整独立证据ZIP](backend-independent-1c592433-incremental.zip)。F的证据包不是本附件。

**结论：指定三项遗留缺陷在本次独立增量范围内全部通过；没有确认的业务失败。该结论不代表整个项目或生产环境验收通过。**

实际被测提交为 PR37 `1c5924338e21caaed0f5ea5c76a33048bbce98dc`。独立 checkout 使用固定提交，未改业务源码。Windows 幻14air，Python 3.12.13、Paddle 3.2.0、PaddleOCR 3.7.0、PaddleX 3.7.2；全部测试使用新建 loopback API、独立 SQLite 和上传目录。用户原工作区的三个未提交 EDI 路径保持原样。

| 项目 | 本次结果 | 相比旧 `fca14f5` 的变化 |
|---|---|---|
| 新加坡／澳大利亚 | **通过，126/126 字段**；仅复测原来失败的42票126份文本PDF。Melbourne 36、Sydney 39、Singapore 51项原文均保留，请求故意填US仍按原文归一AU/SG | 旧结果126项 `NORMALIZE_FAILED`，现在全部 `EXTRACTED` |
| PKGS 20 | **通过**；原始T恤PL实际新VL推理，9/9检查，包装数20且单位null，数量500、净150、毛170、体积1.68正确，没有生成金额，原件下载字节一致。另13项国别／单位边界及保存结果比较复算通过，未知包装单位保持 `NOT_CHECKED` | 旧默认 `CARTON` 已消除；比较复算不计作另一次新推理 |
| 原件／中断收尾 | **通过，58/58检查**；四票12份旧扫描原件、一票部分完成的3份原件、另一次旧SHP-00001三扫描原件的真实VL推理中断。读取前清单与原件齐全，实际杀新建API并重启，下载全部一致；已完成文件保持 `EXTRACTED`，其余 `FAILED/TASK_INTERRUPTED`，第五活动票429 | 旧仅第一原件落盘、另两份404、文件仍 `PARSING` 的反例已消除。48项使用读取入口暂停，另10项为真实模型正在计算，没有读入／输出mock |

真实扫描链路已独立运行：原始扫描PDF → 图像 → PaddleOCR-VL-1.6 → 本地BF16 llama推理 → 未修改的业务抽取 → 公开响应／报告，约85.08秒。原始模型输出与实际引擎日志均保留。GGUF、投影器、PP-DocLayoutV3的哈希与F固定清单完全相同；本机引擎为Windows b11560、NVIDIA Vulkan，F服务器为Linux b11429、CPU，不能外推为生产CPU等价或完整模型准确率证明。

版本关系已核对：main `d223d7c` 是候选祖先；F全材料测试是 `333a711`，正式运行代码是 `831e90f5`，最终候选是 `1c592433`。`333a711`之后业务app只新增health版本标识，`831e90f5`之后只变更文档／证据／探针期限。只读正式 `/health` 返回200，`release_revision=831e90f5b7c98f7f39ba86e52161fd75cc8564e2`。上述PR／CI状态是验收时记录，固定CI38275929518成功。发布时PR37头为 `bb40043fe402a77d49dd48c4f2b6e9b3301a5da9`（open、非draft、未合并）；应用、测试／工具和部署脚本blob与实际被测 `1c5924338e21caaed0f5ea5c76a33048bbce98dc` 一致，仅环境示例、四篇文档和F证据ZIP变化，未对新头重新运行测试。完整版本证据（ZIP内 `evidence/source-relationships.json`）。

两个固定ZIP的SHA256、CRC均正确；旧包顶层1541项清单通过。T恤子目录旧清单有3项说明／金标文件哈希过期，三份PDF本身均一致；未修改金标或原件。材料审计（ZIP内 `evidence/material-integrity.json`）。本次49份新返回及F保存的128份返回通过固定候选Schema／引用／计数校验；后者只是材料复核，未计入新HTTP或新模型推理。131份不同原件测试后哈希不变。初版验收断言误将 `parse_method` 查在documents，已按契约改查extractions；初始评估和修正说明保留，未改实际响应、未重复推理。

**未运行／剩余边界：**正式CPU环境等价、完整浏览器和D私有B1–B6、地址比较、完整EDI成功解析、法规适用、全模板准确率及容量验证。本次无执行阻塞；子清单过期是材料维护问题，不影响已核验原件。验收阶段没有上传生产任务、重启生产、使用聊天凭据、push、发评论、合并或部署；本次发布仅增加脱敏验收材料和通知；F的 `accept-production.py`／`accept_server_restart.py` 均未执行。

核心证据：国别检查（ZIP内 `evidence/country/summary.json`）、新VL输出（ZIP内 `evidence/new-vl/new-raw-model-output.json`）、新VL检查（ZIP内 `evidence/new-vl/checks.json`）、真实VL中断（ZIP内 `evidence/interruption/live-vl/checks.json`）、排队中断（ZIP内 `evidence/interruption/active-and-queued/checks.json`）、部分完成中断（ZIP内 `evidence/interruption/partly-complete/checks.json`）、边界检查（ZIP内 `evidence/boundary-checks.json`）。复现方法见 ZIP内 `REPRODUCE.md`。
