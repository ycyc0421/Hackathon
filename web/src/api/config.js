/**
 * 前后端切换点。
 *
 * mock / 真实后端在运行时切换，不用改代码、不用重新构建：
 *   1. URL 参数 ?mock=1 / ?mock=0（优先级最高，并写入 localStorage 记住选择）
 *   2. localStorage 里已记住的选择
 *   3. 默认 true（mock）
 * 顶栏的数据源切换器走同一套（见 App.vue），切换后整页刷新让所有状态归零。
 */

const STORAGE_KEY = 'app.useMock'

/** 模块初始化时解析一次：URL 参数 > localStorage > 默认 mock */
function resolveInitial() {
  try {
    const params = new URLSearchParams(window.location.search)
    const fromUrl = params.get('mock')
    if (fromUrl === '0' || fromUrl === '1') {
      const value = fromUrl === '1'
      window.localStorage.setItem(STORAGE_KEY, value ? '1' : '0')
      return value
    }
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (saved === '0' || saved === '1') return saved === '1'
  } catch {
    // localStorage 不可用（隐私模式等）时静默落到默认 mock
  }
  return true
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
export const POLL_MAX_ATTEMPTS = 60 // 90 秒

/** 轮询超过这个时长仍未结束时，提示"处理时间较长"，但不放弃等待 */
export const SLOW_POLL_MS = 90_000

/** 网络/服务端错误的重试参数：最多 3 次尝试，间隔 1s / 2s / 4s */
export const RETRY_MAX_ATTEMPTS = 3
export const RETRY_BASE_DELAY_MS = 1000
