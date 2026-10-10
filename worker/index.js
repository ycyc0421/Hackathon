export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url)

    // API 代理：后续接入后端时取消注释并填写后端地址
    // if (url.pathname.startsWith('/api/')) {
    //   const backendUrl = new URL(request.url)
    //   backendUrl.host = 'your-backend.example.com'
    //   return fetch(backendUrl, request)
    // }

    // 静态文件服务
    try {
      // 使用 env.ASSETS 绑定来获取静态资源
      return await env.ASSETS.fetch(request)
    } catch (e) {
      // 出错时返回 index.html（SPA 路由降级）
      try {
        const indexRequest = new Request(`${url.origin}/index.html`, request)
        return await env.ASSETS.fetch(indexRequest)
      } catch (err) {
        return new Response('Not found', { status: 404 })
      }
    }
  },
}
