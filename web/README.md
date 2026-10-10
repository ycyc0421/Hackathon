# 跨境单证合规校验 - 前端

Vue 3 单页应用，四个页面：上传、差异、报告、评测。

## 开发

```sh
npm install
npm run dev      # http://localhost:5173
```

开发期默认使用 `src/mock/` 下的示例数据。

## 构建

```sh
npm run build    # 产出 dist/
```

## 部署

### Cloudflare Workers（当前方案）

根目录的 `wrangler.toml` 已配置 Workers + Assets 绑定。推送到 `main` 分支时 GitHub Actions 自动部署（见 `.github/workflows/deploy.yml`）。

手动部署：

```sh
# 仓库根目录
cd web && npm run build && cd ..
npx wrangler deploy
```

### 其他静态托管

`dist/` 可直接部署到任何静态服务器：

- Nginx / Apache：设为根目录或子目录均可（已配置 `base: './'`）
- GitHub Pages / Vercel / Netlify：上传 `dist/` 内容

## 接口切换

默认 Mock 数据。接真实后端：

1. 修改 `src/api/config.js`：`USE_MOCK = false`
2. 修改 `vite.config.js`：取消注释 `proxy` 配置并填入后端地址
3. 重启 dev server

前端代码无需改动。

## 目录结构

```
src/
├── api/
│   ├── config.js       Mock 开关、后端地址、轮询参数
│   ├── index.js        数据访问层
│   ├── labels.js       状态枚举中文文案
│   └── formatters.js   字段渲染
├── components/         StatusBadge、NoticeBar、EmptyState、SkeletonBlock、ErrorBoundary
├── pages/              UploadPage、DiffPage、ReportPage、EvalPage
├── mock/               示例数据
└── styles.css          全局样式
```

## 技术约束

- 依赖：仅 `vue` + `vite` + `@vitejs/plugin-vue`
- 无路由库（四页用条件渲染）
- 无状态管理库
- 无 UI 组件库
- 无 HTTP 客户端库

设计上保持轻量，便于快速迭代。
