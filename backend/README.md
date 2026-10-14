# 后端模块：单票多品名单证核验与合规引擎

基于 FastAPI 构建的跨境物流单证核验后端服务。负责接收同一票货物的多份单证文件，执行版面解析、字段抽取、单位归一化、多品名行对齐、跨文件比对与目的国规则匹配，并提供结构化报告导出、人工修正重算与系统评测读取接口。

对外数据结构严格遵循 [`docs/schema/check-task.schema.json`](../docs/schema/check-task.schema.json)、[`docs/schema/report-content.schema.json`](../docs/schema/report-content.schema.json) 与 [`docs/schema/evaluation.schema.json`](../docs/schema/evaluation.schema.json)。

---

## 本地启动

建议使用 Python 3.12（与生产环境一致）。在仓库根目录执行：

```sh
python3.12 -m venv backend/.venv
. backend/.venv/bin/activate
python -m pip install -r backend/requirements.txt
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

> Windows PowerShell 可使用 `python -m venv backend/.venv` 创建虚拟环境，随后执行 `backend\.venv\Scripts\Activate.ps1`。如需自定义环境变量，可将 `backend/.env.example` 复制为 `backend/.env`，并在启动命令末尾追加 `--env-file backend/.env`。

启动后可访问交互式接口文档：<http://127.0.0.1:8000/docs>。本地前端通过 `VITE_PROXY_API=http://127.0.0.1:8000 npm --prefix web run dev` 即可代理连接。

---

## 核心 API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/v1/checks` | 上传单证并创建检查任务（`multipart/form-data`），返回 `task_id` 与初始状态 |
| `GET` | `/api/v1/checks/{task_id}` | 轮询任务进度与逐文件解析状态，终态时返回完整比对结果 |
| `GET` | `/api/v1/checks/{task_id}/report` | 获取结构化报告（`view=content`）或完整证据与审计归档（`view=archive`） |
| `GET` | `/api/v1/checks/{task_id}/corrections` | 获取当前任务的结果指纹（`result_hash`）与历史人工修正审计链 |
| `POST` | `/api/v1/checks/{task_id}/corrections` | 提交人工修正并触发派生任务重算（不重跑 OCR，保留原件证据） |
| `GET` | `/api/v1/checks/{task_id}/files/{file_id}` | 下载任务保存的原始单证文件字节 |
| `GET` | `/api/v1/evaluation/latest` | 读取最新发布的固定数据集评测摘要（无结果时返回 `NOT_RUN`） |
| `GET` | `/api/v1/evaluation/runs` | 读取最近发布的评测历史批次列表（最多 30 份） |
| `GET` | `/api/v1/rules/sources` | 查询目的国规则关联的官方法规来源目录与动态监测状态 |
| `GET` | `/api/v1/capabilities` | 查询当前实例支持的单证格式、上传限额与 OCR 通道就绪状态 |

### 请求与错误规范

- **上传限制**：单次最多上传 10 份文件，单文件上限 20 MiB。`files` 与两位国家代码 `destination_country` 必填。
- **错误分层**：
  - 请求参数不合法（400）、文件超限（413）、任务不存在（404）、并发队列已满（429）等请求级错误直接返回非 2xx 与统一 `{ "error": { "code", "message" } }` 结构。
  - 任务创建后的单文件解析失败或版式异常，通过 2xx 响应中的任务状态（`PARTIAL` / `FAILED`）、文件级 `process_status` 及任务级 `errors[]` 表达。

---

## 处理流水线与结果语义

1. **逐文件增量进度**：任务创建后按上传顺序逐份解析文件。每份文件开始解析时写入 `PARSING` 快照，完成后更新为 `EXTRACTED`、`FAILED` 或 `UNSUPPORTED`，并实时提交至 SQLite，供前端平稳展示真实进度。
2. **多品名对齐与比对**：
   - `items[]` 为任务内的商品目录，商品级字段与比对项通过 `item_id` 关联，整票级字段的 `item_id` 为 `null`。
   - 跨文件行序不同时，优先按商品货号（`item_code`）、其次按规范化品名描述对齐；无法可靠对齐时标记为 `NOT_CHECKED` 并附带原因，绝不按行号盲目猜测。
3. **严格的结论边界**：
   - `MATCH` 仅表示参与比对的已识别值一致，不代表整票合规通过。
   - `NOT_CHECKED`、`UNRECOGNIZED`、`SINGLE_SOURCE` 及解析失败均独立呈现，不混同于“无问题”。
   - `canonical_value` 恒为 `null`，系统只指出差异并提供 `suggested_action` 核对建议，不替业务人员裁定哪份单证正确。

---

## 目录结构

```text
backend/
├── app/
│   ├── main.py             FastAPI 路由、并发控制与统一错误响应
│   ├── models.py           内部领域模型与状态机校验
│   ├── frontend_view.py    内部模型到公开 CheckTask Schema 的投影层
│   ├── report_content.py   报告契约 v2（content / archive 视图）投影层
│   ├── doc_profile.py      单证类型与必需/可选/不适用字段规则表
│   ├── evaluation.py       评测结果读取与计分一致性校验
│   ├── store.py            SQLite 任务持久化、修正审计与旧版 JSON 兼容导出
│   ├── rules/              目的国规则配置、官方来源目录与监测读取
│   └── pipeline/           PDF/OCR 解析、字段抽取、归一化、行对齐与交叉比对
├── samples/                01–11 合成单证、challenge 挑战集与专项回归材料
├── tools/                  数据集评测（evaluate_dataset.py）、OCR 探针与验收脚本
├── tests/                  pytest 自动化测试套件
├── requirements.txt        核心服务运行依赖
└── requirements-ocr.txt    本地 PaddleOCR 扩展依赖
```

---

## OCR 引擎与生产运行配置

系统支持文本层 PDF 直读与扫描件/图片 OCR 识别。生产环境采用 **PaddleOCR-VL-1.6**（结合 `PP-DocLayoutV3` 版面分析与 `llama.cpp` GGUF CPU 推理服务）：

- **启用主模型（VL 通道）**：设置 `PADDLE_OCR_ENABLED=1`、`PADDLE_OCR_ENGINE=vl`、`PADDLE_VL_SERVICE_URL=http://127.0.0.1:18082`。保留实际区域、HTML 表格网格、页码与原始读数；遇到无法唯一定位的复杂多表或缺失关键列时显式标记失败。
- **启用传统通道（Legacy）**：安装 `requirements-ocr.txt` 后设置 `PADDLE_OCR_ENABLED=1`、`PADDLE_OCR_ENGINE=legacy`（使用 `PP-StructureV3` + 常规 OCR）。对数字 `0` 与字母 `O` 的单位混淆做受控校正并附加 `OCR_AUTO_CORRECTED` 告警与 `LOW_CONFIDENCE` 标记。
- **资源与队列保护**：原件全部落盘后开始推理；API 最多同时接纳 4 票运行或排队任务，超出时返回 HTTP 429 `CHECK_QUEUE_FULL`。服务重启时会将未完成的任务收尾为 `FAILED / TASK_INTERRUPTED`，原件保留可下载。

详见 [OCR 主模型交付说明](../docs/PADDLE_VL_DELIVERY.md) 与 [部署运维手册](../docs/部署运维.md)。

---

## 自动化测试与验证

在仓库根目录安装测试依赖并执行 pytest：

```sh
python -m pip install -r backend/requirements.txt -r requirements-test.txt
npm ci
python -m pytest                       # 运行全部后端回归（含接口、样例与 Schema 校验）
python -m pytest -m "not integration"  # 仅运行快速单元测试
python -m pytest data                  # 运行 SQLite 数据层测试
python -m pytest deploy                # 运行部署与回退逻辑测试
```

默认测试环境自动隔离临时 SQLite 数据库与上传目录，并关闭外部 OCR/LLM 调用以确保确定性。如需针对真实 OCR 通道运行探针：

```sh
export PADDLE_OCR_ENABLED=1
python backend/tools/run_ocr_probe.py 11_de_multiitem_mixed
```
