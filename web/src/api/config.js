/**
 * 前后端切换点。
 *
 * mock / 真实后端在运行时切换，不用改代码、不用重新构建：
 *   1. URL 参数 ?mock=1 / ?mock=0（优先级最高，并写入 localStorage 记住选择）
 *   2. localStorage 里已记住的选择
 *   3. 默认真实后端
 *
 * 注意参数位置：路由是 hash 模式，查询串必须写在 hash **之前**
 * （`/?mock=1#/upload`）。写成 `/#/upload?mock=1` 时 query 落在 hash 内部，
 * location.search 为空，参数读不到——旧文档与演示脚本都踩过这个坑。
 */

const STORAGE_KEY = 'app.useMock'

/**
 * 读取数据源参数：优先 location.search，其次 hash 内 query。
 * hash 内分支是对旧链接（`#/?mock=1`）的兼容，同时兜住「用户把参数
 * 写在 hash 里」的直觉写法——静默失效比报错更难排查。
 */
function readMockParam() {
  const fromSearch = new URLSearchParams(window.location.search).get('mock')
  if (fromSearch === '0' || fromSearch === '1') return fromSearch
  const hash = window.location.hash
  const q = hash.indexOf('?')
  if (q === -1) return null
  const fromHash = new URLSearchParams(hash.slice(q + 1)).get('mock')
  return fromHash === '0' || fromHash === '1' ? fromHash : null
}

/** 模块初始化时解析一次：URL 参数 > localStorage > 默认真实后端 */
function resolveInitial() {
  try {
    const fromUrl = readMockParam()
    if (fromUrl !== null) {
      const value = fromUrl === '1'
      try { window.localStorage.setItem(STORAGE_KEY, value ? '1' : '0') } catch { /* URL 选择不依赖存储写入成功 */ }
      return value
    }
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (saved === '0' || saved === '1') return saved === '1'
  } catch {
    // localStorage 不可用（隐私模式等）时静默落到默认真实后端
  }
  return false
}

let useMock = resolveInitial()

/** 当前数据源。api 层每次请求时调用，保证拿到切换后的值 */
export function isMock() {
  return useMock
}

/**
 * 切换数据源并写入 localStorage。返回新值。
 * 只负责切状态，调用方（顶栏切换器）随后整页刷新，
 * 避免旧任务、旧缓存混到新的数据源下。
 */
export function setMock(value) {
  useMock = Boolean(value)
  try {
    window.localStorage.setItem(STORAGE_KEY, useMock ? '1' : '0')
  } catch {
    /* 记不下来就只影响本次会话 */
  }
  return useMock
}

/** 真实后端地址。可用构建环境变量 VITE_API_BASE 覆盖，默认走同源 /api/v1 */
export const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

/** 轮询参数。取自 docs/数据契约.md 第四节第 1 项的当前处理方式 */
export const POLL_INTERVAL_MS = 1500
export const POLL_MAX_ATTEMPTS = 1200 // 最多等待 30 分钟，包含 CPU 模型冷启动和排队

/**
 * 软提示线：轮询超过这个时长仍未结束时，提示"处理时间较长"，但不放弃等待。
 * 30 秒后展示提示；任务仍在运行时继续查询，取消操作仍立即生效。
 */
export const SLOW_POLL_MS = 30_000

/** 单次请求的应用层截止（fetch 与 XHR 上传共用），见 api/request.js */
export { REQUEST_TIMEOUT_MS } from './request.js'

/** 网络/服务端错误的重试参数：最多 3 次尝试，间隔 1s / 2s / 4s */
export const RETRY_MAX_ATTEMPTS = 3
export const RETRY_BASE_DELAY_MS = 1000
