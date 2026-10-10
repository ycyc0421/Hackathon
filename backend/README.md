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

`items[]` 是任务内的商品目录；商品级字段和比对使用 `item_id` 关联。
行序不一致时优先按货号、其次按描述对齐；无法可靠对齐时给 `NOT_CHECKED`，不猜测一致或冲突。
`suggested_action` 只提供可执行的核对建议，不指定哪份文件正确；无可靠建议时为 `null`。

## 结果判读与前端联调

- 对外结果中，`items[]` 是商品目录；`extractions[].fields[]` 的商品级字段和 `comparisons[]` 用 `item_id` 关联它，票级字段的 `item_id` 为 `null`。后端内部虽有单文件商品行与对齐状态，对外 Schema 不直接返回 `line_items[]` 或 `alignment_status`。提单只有整票汇总时，不要求它提供商品行。
- 行可靠对应后才比较商品级字段；只有一份文件提供某商品行时，对应字段最多给 `SINGLE_SOURCE`；多份文件有疑似行却无法可靠对应时给 `NOT_CHECKED`，并在 `note` 说明原因。单品名票的 `items[]` 可以为空，票级字段仍可比对。
- `MATCH` 只表示**参与比对的已识别值一致**，不是整票合规通过。`NOT_CHECKED`、`UNRECOGNIZED`、`SINGLE_SOURCE` 和解析失败都不能当作一致；前端应展示状态、来源文件、原值及 `note`。`suggested_action` 是核对建议，不代替结论。
- 有文件解析失败时，该文件进入 `errors[]`，任务可能为 `PARTIAL` 或 `FAILED`；前端需按任务状态显示失败。表格疑似多品名却无法可靠切行时，后端给 `MULTI_LINE_ITEMS_SUSPECTED` 警告并降级，不把猜出的行当成确定结果。

- ## 项目结构

```text
backend/
├── app/
│   ├── main.py             FastAPI 路由与统一错误响应
│   ├── models.py           内部数据模型与状态校验
│   ├── frontend_view.py    将内部结果映射到对外 Schema
│   ├── doc_profile.py      单证类型与适用字段的临时规则表
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
- 图片和无文本层 PDF 需要配置 OCR／多模态识别服务；未配置时显式返回解析失败。
- 目的国规则是未核实的演示规则，结果保留“演示规则·未经核实”标记，不能作为正式合规结论。
- `confidence` 与 `bbox` 暂为 `null`；人工修正、报告导出和 EDI 解析尚未实现。
- 任务结果落盘并可在重启后读取；处理中的任务重启恢复尚未实现。正式部署需接入持久任务队列或数据库。
- `app/doc_profile.py` 的单证适用字段表为临时版，待数据侧正式表替换。
