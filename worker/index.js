import { getAssetFromKV } from '@cloudflare/kv-asset-handler'

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
      return await getAssetFromKV(
        {
          request,
          waitUntil: ctx.waitUntil.bind(ctx),
        },
        {
          ASSET_NAMESPACE: env.__STATIC_CONTENT,
          ASSET_MANIFEST: __STATIC_CONTENT_MANIFEST,
        }
      )
    } catch (e) {
      // 404 时返回 index.html（SPA 路由）
      if (e.status === 404) {
        try {
          return await getAssetFromKV(
            {
              request: new Request(`${url.origin}/index.html`, request),
              waitUntil: ctx.waitUntil.bind(ctx),
            },
            {
              ASSET_NAMESPACE: env.__STATIC_CONTENT,
              ASSET_MANIFEST: __STATIC_CONTENT_MANIFEST,
            }
          )
        } catch (err) {
          return new Response('Not found', { status: 404 })
        }
      }
      return new Response('Error', { status: 500 })
    }
  },
}
