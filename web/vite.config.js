import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// base 用相对路径：dist/ 丢到任何静态服务器的任意子目录都能直接打开，
// 不需要额外配置（部署时少一个坑）。
export default defineConfig({
  plugins: [vue()],
  base: './',
  server: {
    port: 5173,
    // mock/真实后端的切换是运行时的（URL 参数 ?mock=0 或顶栏数据源切换器），
    // 前端代码不用改、不用重新构建。真实后端默认走同源 /api/v1：
    // - 本地后端（8000 端口）：VITE_PROXY_API=http://127.0.0.1:8000 npm run dev
    // - 远端已部署后端：VITE_PROXY_API=https://hackathon.ychome.net npm run dev
    // 不设 VITE_PROXY_API 时也可直连（后端开发期 allow_origins=["*"]，
    // 配合 VITE_API_BASE 指向后端地址）。
    proxy: process.env.VITE_PROXY_API
      ? {
          '/api': {
            target: process.env.VITE_PROXY_API,
            changeOrigin: true,
          },
        }
      : undefined,
  },
})
