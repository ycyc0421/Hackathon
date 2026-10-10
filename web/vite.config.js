import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// base 用相对路径：dist/ 丢到任何静态服务器的任意子目录都能直接打开，
// 不需要额外配置（部署时少一个坑）。
export default defineConfig({
  plugins: [vue()],
  base: './',
  server: {
    port: 5173,
    // 接真实后端时取消注释，并把 src/api/config.js 的 USE_MOCK 关掉。
    // 前端代码不用改。
    // proxy: {
    //   '/api': {
    //     target: 'http://127.0.0.1:8000',
    //     changeOrigin: true,
    //   },
    // },
  },
})
