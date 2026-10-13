# 前端：单证上传、差异、报告与评测

Vue 3 + Vite 单页应用，四个页面通过条件渲染切换。公开数据结构见[数据契约](../docs/数据契约.md)，后端启动见[后端说明](../backend/README.md)。

## 本地开发

命令从仓库根目录运行，需要 Node.js 20：

```sh
npm ci
npm --prefix web ci
npm --prefix web run dev
```

访问 Vite 输出的本地地址。真实模式需要另开终端启动后端。使用环境变量启用 Vite 开发代理，无需改源码：

```sh
VITE_PROXY_API=http://127.0.0.1:8000 npm --prefix web run dev
```

PowerShell 先设置 `$env:VITE_PROXY_API = 'http://127.0.0.1:8000'`，再运行开发命令。也可把代理目标设为 `https://hackathon.ychome.net` 连接已部署后端；目标地址不带 /api/v1。代理只在开发服务器生效，浏览器仍请求同源 /api/v1，无需额外跨域配置。

## 示例与真实模式

默认示例模式使用 `src/mock/`，不会上传文件至后端。顶栏可切换模式，选择保存到浏览器；URL 参数优先于保存值：`?mock=0` 使用真实接口，`?mock=1` 使用示例数据。

前端默认请求同源 `/api/v1`。本地确需连接其他服务时，可在启动或构建前设置 `VITE_API_BASE` 为含 `/api/v1` 的基础地址；这是构建时配置，变更后重启开发服务或重新构建。跨源服务还需正确配置 CORS。

线上统一使用 `https://hackathon.ychome.net`。首次访问默认示例不表示后端不可用，验收必须切到真实模式。

## 验证与构建

```sh
npm run validate
node --test tests/*.test.mjs
npm --prefix web run build
```

构建产物为 `web/dist`，不提交 Git。CI 构建后与同一提交的后端一起打包，Nginx 提供静态文件并代理 API，见[工作流说明](../.github/workflows/README.md)。仓库保留的 Worker、wrangler 与旧 npm deploy 命令是历史路径，不是当前生产发布入口。

纯静态托管只提供页面；真实模式仍需可访问的 API 及对应代理或跨源配置。构建成功不能代替上传、差异查看、失败状态与评测空态的浏览器检查。

## 目录与边界

| 位置 | 职责 |
|---|---|
| `src/api/config.js` | 模式选择、API 地址、轮询参数 |
| `src/api/index.js` | 统一请求入口，页面不直接 fetch |
| `src/api/labels.js` | 枚举的中文文案与状态样式 |
| `src/api/formatters.js` | 字段显示格式 |
| `src/pages/` | 上传、差异、报告、评测 |
| `src/components/` | 共享交互组件 |
| `src/utils/needsReview.js` | 人工复核条目口径 |
| `src/report/` | 导出 HTML 报告的排版与打印样式 |
| `src/design-tokens.css`、`src/styles.css` | 设计变量与全站样式 |

- 上传到终态共用一个任务视图；阶段条、文件列表与等待时间持续可见，完成后就地更新。上传 100% 只代表字节发完，创建任务仍可能等待。
- 后端逐份发布 PARSING 及文件终态，前端用已选文件名补齐尚未开始的条目；已处理计数包括 EXTRACTED、FAILED、UNSUPPORTED。短任务可能在两次轮询间完成，页面不补播未观察到的状态。
- 多品名依赖后端商品目录与 item_id；字段中文名直接使用 label。
- MATCH 表示参与值一致，含 LOW_CONFIDENCE 时仍需人工复核；不能据此宣布整票合规。
- 缺置信度、页码或坐标时降级显示；未评测显示“尚未评测”，不能填假数字。
- 报告页展示结果；报告导出与人工修正见 `src/components/WorkflowActions.vue`。导出的 HTML 报告由 `src/report/` 在前端排版生成（后端 `format=html` 已返回 410），另提供归档 JSON 出口保留完整抽取结构与修正审计。
- 当前轮询 1.5 秒一次、最多 60 次，耗时 OCR 可能超出窗口；停止轮询不等于取消任务。
- 上传页扫描件提示仍有“后端仅支持文本 PDF”的旧文案，和已启用 OCR 的生产环境不一致，后续应用改动需修正。

依赖保持 vue、vite、@vitejs/plugin-vue，不引入路由、状态库、UI 库或 HTTP 客户端。设计与动效规范见[设计系统](DESIGN.md)。
