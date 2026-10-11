import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// base 用相对路径：dist/ 丢到任何静态服务器的任意子目录都能直接打开，
// 不需要额外配置（部署时少一个坑）。
export default defineConfig({
  plugins: [vue()],
  base: './',
  server: {
    port: 5173,
    // 真实后端跑在 8000 端口时取消注释即可；mock/真实后端的切换是运行时的
    //（URL 参数 ?mock=0 或顶栏数据源切换器），前端代码不用改、不用重新构建。
    // 后端跨域开发期 allow_origins=["*"]，不走 proxy 直连 http://127.0.0.1:8000 也行。
    // proxy: {
    //   '/api': {
    //     target: 'http://127.0.0.1:8000',
    //     changeOrigin: true,
    //   },
    // },
  },
})
