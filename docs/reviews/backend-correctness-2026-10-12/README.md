# 后端正确性审核：报告与最小验证数据

SHP-00002 在未调用 OCR 的文本层路径上就能复现错误金额、净毛重混淆和商品行丢失。旧版与最新候选版的报告分开提供；候选版还存在结构化 JSON 的逐行数量缺失被隐藏的问题。

## 固定版本与材料

- [旧版审核报告](旧版后端审核报告.md)：main 的历史提交 `76ffb556af2c6fa0193172bcf5f71cd72d7cf912`。
- [最新候选版审核报告](最新后端分支审核报告.md)：PR #37，`feat/backend-workflow-rules@685d6e15618cb882b5586cea1341f16527dee18d`。
- [完整验证材料 ZIP](backend-review-evidence.zip)：本目录中的报告、原件、复现脚本和证据。下载后解压，从解压根目录执行下面的命令。
- [SHP-00002 原件](inputs/SHP-00002)：商业发票、形式发票、装箱单；3 份 PDF 与用户提供压缩包内的原文件逐字节相同。
- [JSON 漏填数量输入](inputs/json_missing_quantity)：两份可供新分支 JSON 入口验证的输入，装箱单 SKU-B2 刻意省略 quantity。
- [OCR 对照记录](evidence/ocr-reference/ocr-validation.json)：PaddleOCR-VL-1.6 BF16/Q8 对这三页各 57 项选定字段检查；另附真实双表输出和传统 OCR 文本。
- [SHA-256 清单](MANIFEST.sha256)：包内各文件校验值。

## 本地组件复现

以下命令以 Windows PowerShell 为例。需要 Git、Python 和网络来安装后端普通依赖；复现脚本禁用 OCR 与外部模型，不要求下载模型或连接生产服务器。

```powershell
git clone https://github.com/ycyc0421/Hackathon.git Hackathon-source
git -C Hackathon-source worktree add --detach ../Hackathon-previous 76ffb556af2c6fa0193172bcf5f71cd72d7cf912
git -C Hackathon-source worktree add --detach ../Hackathon-latest 685d6e15618cb882b5586cea1341f16527dee18d
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r Hackathon-source/backend/requirements.txt
.\.venv\Scripts\python.exe reproduce_root_causes.py --repo Hackathon-previous --out evidence/recheck-previous
.\.venv\Scripts\python.exe reproduce_root_causes.py --repo Hackathon-latest --out evidence/recheck-latest
.\.venv\Scripts\python.exe reproduce_json_missing_quantity.py --repo Hackathon-latest --out evidence/recheck-json.json
```

两份 PDF 诊断结果目前均为 `items=0, comparisons=11, conflicts=0, unrecognized=3`，CI/PI 金额误为 1，PL 毛重误为 463.60。JSON 探针目前为 `bug_reproduced=true, actual_status=SINGLE_SOURCE`；应为 `MISSING_IN_SOME`。诊断退出码 0 表示执行完成，不表示验收通过。

## 修复后的最低验收

- CI/PI/PL 保留各自编号 CI-00002、PI-00002、PL-00002，不能要求三种编号相同。
- 按 SKU 识别 3 行商品；SKU-0002-1 数量 880/880/888 必须报冲突并保留双方原文。其他两项为 5000、4000。
- PL 合计 55 箱，净重 463.60 KG、毛重 503.43 KG、体积 1.073 CBM；行箱数 22/25/8 与合计分层保存。
- CI/PI 金额为 GBP 5049.60；PL 无金额时不生成金额。
- 公司名和描述来自实际内容；字段缺失、解析失败、归一失败、不适用分开表达；关键比较未完成时不显示整体通过。
- 合法合并单元格和主体表/商品表共存的页面可可靠处理，不能靠猜列、选第一张表或静默丢表。
- JSON 的 PL SKU-B2 quantity 为 MISSING_IN_DOC；B2 数量比较为 MISSING_IN_SOME，A1 数量仍 MATCH。

## 证据边界与发布副本

仅验证系统正确性，不判断构造单据是否满足法规。第二组“500 件、USD 1400”的 T 恤扫描原件不在用户提供的 ZIP 内，未随包上传，也未声称逐项定位完成。57 项模型对照仅覆盖三页选定字段，不能当作完整数据集准确率。

公开材料含构造单据、代码与诊断输出；不含服务凭据、生产数据库、模型权重。发布副本统一文本编码并移除无关本机绝对路径；原 PDF 的内容与哈希不变。所有证据均来自本地源码和组件验证，没有修改生产部署。
