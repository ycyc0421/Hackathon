# 后端：单票多品名单证核验

上传同一票货物的多份单证，抽取整票及商品行字段，跨文件比对并返回可追溯结果。
对外返回以 [`docs/schema/check-task.schema.json`](../docs/schema/check-task.schema.json) 为准。

## 运行

需要 Python 3.12+。在仓库根目录执行：

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

接口文档：<http://127.0.0.1:8000/docs>。本地前端可通过 Vite 的 `/api` 代理连接。

## 接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/v1/checks` | 上传并创建任务；返回 `task_id` 与当前状态，快速完成时直接返回结果 |
| `GET` | `/api/v1/checks/{task_id}` | 轮询状态及读取结果 |
| `GET` | `/api/v1/evaluation/latest` | 评测状态；尚无正式金标评测时返回 `NOT_RUN` |

`POST` 使用 `multipart/form-data`：`files` 与两位国家代码 `destination_country` 必填；
`destination_country_name`、`trade_mode`、`declared_currency`、`notes` 可选。
最多上传 10 份，单份上限 20 MB。未完成的任务返回 `PENDING` 或 `PROCESSING`。
已创建任务的处理失败通过 `GET` 的 `status: FAILED` 与 `errors[]` 表示；参数错误、超限、
未知任务和内部错误返回非 2xx 与统一的 `error.code` / `error.message`。

前端可按错误码映射文案：

| 位置 | `code` | 含义 |
|---|---|---|
| 非 2xx `error.code` | `INVALID_REQUEST`、`INVALID_DESTINATION_COUNTRY`、`INVALID_CURRENCY`、`NO_FILE` | 请求参数错误（400） |
| 非 2xx `error.code` | `FILE_TOO_LARGE`、`TOO_MANY_FILES` | 上传超限（413） |
| 非 2xx `error.code` | `TASK_NOT_FOUND`、`NOT_FOUND` | 任务或路径不存在（404） |
| 非 2xx `error.code` | `METHOD_NOT_ALLOWED`、`HTTP_ERROR`、`INTERNAL_ERROR`、`CONTRACT_VIOLATION` | 方法不允许、其他 HTTP 错误或服务端错误 |
| 任务 `errors[].code` | `DOC_PARSE_FAILED`、`UNSUPPORTED_FILE_TYPE`、`MULTI_LINE_ITEMS_SUSPECTED` | 单文件解析失败、格式不支持、品名表格未可靠切行 |
| 任务 `errors[].code` | `RULES_UNVERIFIED`、`ALL_DOCUMENTS_FAILED`、`INTERNAL_ERROR`、`CONTRACT_VIOLATION` | 演示规则警告、全部文件失败或处理异常 |

已创建任务的处理错误需先看任务 `status` 和 `errors[]`；不能仅凭 GET 返回 200 显示“检查完成”。

`items[]` 是任务内的商品目录；商品级字段和比对使用 `item_id` 关联。
行序不一致时优先按货号、其次按描述对齐；无法可靠对齐时给 `NOT_CHECKED`，不猜测一致或冲突。
`suggested_action` 只提供可执行的核对建议，不指定哪份文件正确；无可靠建议时为 `null`。

## 结果判读与前端联调

- 对外结果中，`items[]` 是商品目录；`extractions[].fields[]` 的商品级字段和 `comparisons[]` 用 `item_id` 关联它，票级字段的 `item_id` 为 `null`。后端内部虽有单文件商品行与对齐状态，对外 Schema 不直接返回 `line_items[]` 或 `alignment_status`。提单只有整票汇总时，不要求它提供商品行。
- 行可靠对应后才比较商品级字段；只有一份文件提供某商品行时，对应字段最多给 `SINGLE_SOURCE`；多份文件有疑似行却无法可靠对应时给 `NOT_CHECKED`，并在 `note` 说明原因。单品名票的 `items[]` 可以为空，票级字段仍可比对。
- `MATCH` 只表示**参与比对的已识别值一致**，不是整票合规通过。`NOT_CHECKED`、`UNRECOGNIZED`、`SINGLE_SOURCE` 和解析失败都不能当作一致；前端应展示状态、来源文件、原值及 `note`。`suggested_action` 是核对建议，不代替结论。
- 有文件解析失败时，该文件进入 `errors[]`，任务可能为 `PARTIAL` 或 `FAILED`；前端需按任务状态显示失败。表格疑似多品名却无法可靠切行时，后端给 `MULTI_LINE_ITEMS_SUSPECTED` 警告并降级，不把猜出的行当成确定结果。

## 项目结构

```text
backend/
├── app/
│   ├── main.py             FastAPI 路由与统一错误响应
│   ├── models.py           内部数据模型与状态校验
│   ├── frontend_view.py    将内部结果映射到对外 Schema
│   ├── doc_profile.py      单证类型与必需字段表（前三类按已确认规则）
│   ├── store.py            任务存储与已完成结果落盘
│   ├── rules/              目的国演示规则配置
│   └── pipeline/           文件读取、抽取、归一、行对齐、比对与规则检查
├── samples/                01–11 合成单证；challenge/ 为金标预期
├── tools/                  样例生成、接口自检与挑战样例验证
├── requirements.txt        Python 依赖
└── .env.example            可选运行配置示例
```

## 验证与样例

`samples/` 是已生成的合成单证，`tools/` 用于复现和验证核验结果；**启动后端不需要运行这些脚本，也不需要重新生成样例**。
需要验证时，在仓库根目录先执行 `npm install`，再运行：

```powershell
backend/.venv/Scripts/python.exe backend/tools/selftest.py       # 01–08、评测返回及 Schema
backend/.venv/Scripts/python.exe backend/tools/test_compare.py   # 数值、币种、行对齐断言
backend/.venv/Scripts/python.exe backend/tools/test_review_regressions.py  # 审查边界：列序、单位、HS、混合 PDF 等
backend/.venv/Scripts/python.exe backend/tools/run_challenge.py  # 09–11 挑战样例与金标断言
```

| 样例 | 验证内容 |
|---|---|
| `01`–`03` | 单品名一致、冲突、部分解析失败 |
| `04`–`07` | 多品名对齐、行序变化、缺行及无法对齐 |
| `08_de_bilingual_format` | 中英文字段、数字和日期格式差异 |
| `09_us_format_mixed` | 三份单证语言和日期写法不同，但值一致 |
| `10_de_ambiguity_conflict` | 欧式小数、歧义日期、`US$` 币种及真实数量冲突 |
| `11_de_multiitem_mixed` | 四品名、行序变化、跨语言描述及颜色冲突 |

09–11 的预期结果见[金标清单](samples/challenge/金标预期.md)。样例已包含文本层 PDF
与 PNG；重新生成需 `fpdf2`、`Pillow` 和 Windows 字体：
`backend/.venv/Scripts/python.exe backend/tools/make_challenge_samples.py`。
验证输出写入忽略提交的 `backend/.out/`。

## 能力边界

- 文本层 PDF 已用上述合成样例验证；真实复杂版式的抽取准确率尚未评测。
- 图片和无文本层 PDF 可选用本地 PaddleOCR。默认关闭，未配置识别通道时显式返回解析失败。
- 目的国规则是未核实的演示规则，结果保留“演示规则·未经核实”标记，不能作为正式合规结论。
- `confidence` 与 `bbox` 暂为 `null`；人工修正、报告导出和 EDI 解析尚未实现。
- 任务结果落盘并可在重启后读取；处理中的任务重启恢复尚未实现。正式部署需接入持久任务队列或数据库。
- `app/doc_profile.py` 的商业发票、装箱单、提单按已确认最小规则区分必需/可选；其他单证类型及更完整的适用字段表待数据侧确认。

## 本地 PaddleOCR（可选）

在独立 Python 3.12 环境，先按 PaddlePaddle 官方 CPU 渠道安装推理引擎，
再安装 `requirements-ocr.txt`（PaddleOCR 3.7.0 文档解析组件与扫描 PDF 渲染依赖）：

```powershell
python -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
python -m pip install -r backend/requirements-ocr.txt
```

启动后端前设置
`PADDLE_OCR_ENABLED=1`。模型首次推理时下载到本机缓存，模型文件不提交仓库。
文本层 PDF 仍直接读取；图片和扫描页使用 OCR。检测到商品明细表时，
PP-StructureV3 提供行列结构，普通 OCR 提供正文原文。若表格结构、列数或
页面识别不可靠，文件会显式解析失败。OCR 文字可能误识别，例如
`350ML` → `35OML`，结果必须保留原文供人工核对。
两套识别输出仅在数字 `0` 与字母 `O` 混淆、且一方符合明确的数字加单位
格式时，才校正并给 `OCR_AUTO_CORRECTED` 警告。商品字段保留校正前的 OCR
读数作为 `raw_text` / `raw_value`，归一值使用校正后的候选；字段标为
`LOW_CONFIDENCE`，若跨文件比对一致，仍附 `WARNING` 与人工核对说明。其他品名分歧返回
`NOT_CHECKED` 和 `OCR_TEXT_DISAGREEMENT` 警告。
当前本地 OCR 只接受可交叉核验的单张商品表；一页多张表、缺少货号或品名列时，
文件显式解析失败，不丢弃明细后继续给出比对结论。表头支持抽取层已有的中英文列名。

```powershell
$env:PADDLE_OCR_ENABLED = '1'
python backend/tools/run_ocr_probe.py
```

该探针单独运行 09–11 的 PNG，不进入默认 CI；CI 仍只运行无需下载模型的
文本层 PDF 与纯逻辑回归。探针要求所选样例的文件全部经过 OCR 成功处理；11 号
还须保留 4 个商品行并检出颜色差异。自动部署的 Python 选择、OCR 开关和公网扫描
PDF 验证见 [工作流说明](../.github/workflows/README.md#后端主机初始化)。
## SQLite 任务存储

任务与结果已接入 SQLite；默认运行库位于共享 `.data/tasks.sqlite3`，旧 JSON 结果保留并迁入。商品组成员、OCR 证据及警告保存在同事务完整快照中。启动时未完成任务标记为 `FAILED / TASK_INTERRUPTED`，需重新上传。部署迁移与回退说明见根目录 `SQLITE_INTEGRATION.md`。
