# 前端模块：单证上传、差异比对、检查报告与系统评测

基于 Vue 3 + Vue Router + Vite 构建的单页应用。对外数据结构以 [数据契约](../docs/数据契约.md) 与 [报告内容接口](../docs/report-content-api.md) 为准，后端服务启动方式见 [后端说明](../backend/README.md)。

---

## 本地开发与联调

在仓库根目录执行（需 Node.js 20+）：

```sh
npm ci
npm --prefix web ci
npm --prefix web run dev
```

启动后访问 Vite 输出的本地地址。连接本地后端（默认 `http://127.0.0.1:8000`）时，通过环境变量开启开发代理，无需修改源码：

```sh
VITE_PROXY_API=http://127.0.0.1:8000 npm --prefix web run dev
```

> Windows PowerShell 先执行 `$env:VITE_PROXY_API = 'http://127.0.0.1:8000'`，再运行 `npm --prefix web run dev`。代理目标不带 `/api/v1`，浏览器在开发与生产环境均请求同源 `/api/v1`。

---

## 数据源切换（真实后端 / 示例数据）

应用支持在运行时切换真实后端与内置示例数据（`src/mock/`），无需重新构建：

- **真实后端模式（默认）**：首次访问直接连接后端接口；也可通过 `?mock=0` 显式切回。
- **示例数据模式（`?mock=1`）**：使用前端内置的契约样例模拟上传进度、比对结果与评测看板，不向服务器发送文件。顶栏下方常驻提示条标明当前处于示例数据模式。

> 注意：应用采用 Hash 路由，查询参数请置于 `#` 之前（例如 `/?mock=1#/upload`），同时兼容 `#/upload?mock=1` 写法。模式选择会保存在浏览器的 `localStorage` 中。

---

## 校验与构建

```sh
npm run validate               # 校验 JSON Schema 与契约示例
node --test tests/*.test.mjs   # 运行前端逻辑与报告生成单元测试（119 项）
npm --prefix web run build     # 构建生产静态产物（输出至 web/dist）
```

---

## 目录结构

| 路径 | 职责说明 |
|---|---|
| `src/router.js` | Hash 路由表（首页 `/`、上传 `/upload`、差异 `/diff`、报告 `/report`、评测 `/eval`）与路由守卫 |
| `src/state/` | 跨页会话状态（`session.js`）、深浅色主题切换（`theme.js`）、演示场景元数据（`scenarios.js`） |
| `src/api/config.js` | 数据源解析、API 基础路径、轮询与重试参数 |
| `src/api/request.js` | 请求超时控制、取消传播、自动重试、XHR 上传进度与轮询循环 |
| `src/api/index.js` | 统一数据访问入口（页面与组件不直接调用 `fetch`） |
| `src/api/labels.js` | 契约状态枚举的中文文案与语义色映射 |
| `src/api/errors.js` | 后端错误码到用户可读提示的映射 |
| `src/api/formatters.js` | 数值、金额、时间、耗时及状态徽章格式化 |
| `src/report/` | 结构化报告（v2）的前端自包含 HTML 排版与导出（`document.js`、`styles.js`） |
| `src/pages/` | 五个核心页面视图（`HomePage`、`UploadPage`、`DiffPage`、`ReportPage`、`EvalPage`） |
| `src/components/` | 共享组件（原文预览抽屉 `SourcePreview`、并排对照 `ComparePane`、报告导出与修正 `WorkflowActions` 等） |
| `src/utils/` | 待复核判定（`needsReview.js`）、多数派差异计算（`divergence.js`）、报告结论推导（`reportConclusion.js`）、高度自适应过渡（`animateHeight.js`） |
| `src/design-tokens.css` / `src/styles.css` | 双主题设计变量与全站样式 |

---

## 核心交互与降级原则

1. **全生命周期单视图进度**：上传页从文件上传、排队解析到终态保持同一张任务卡片与文件列表就地更新；上传百分比仅表示字节传输进度，轮询窗口最长支持 30 分钟以容纳扫描件 OCR 推理。
2. **启发式扫描件预检**：本地预检未发现 PDF 文本层时，仅提示「疑似扫描件，将通过 OCR 识别」，不阻断提交。
3. **同屏原文核对**：在差异页点击「查看原文」会在页面右侧滑出原件预览抽屉（PDF 自动定位到对应页码，图片原比例展示，EDI/JSON 按纯文本安全渲染），避免新开标签页打断核对视线。
4. **严格的降级展示**：
   - `MATCH` 仅表示参与比对的已识别值一致；若包含 `LOW_CONFIDENCE` 取值，仍归入「需关注」提醒人工复核。
   - 缺失 `confidence`、`bbox` 或 `page` 时自动隐藏对应展示项，不伪造默认值。
   - 规则提示按是否具备 `rule_id` 拆分为「依据规则的提示」与「未经规则校验的提示」两张独立卡片。
   - 评测数据未生成时如实展示「尚未评测」，不填充默认数值。

视觉语言、双主题配色与动效规范详见 [前端设计系统](DESIGN.md)。
