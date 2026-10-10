/**
 * 前后端切换点。
 *
 * 开发期用 mock，后端就绪后把 USE_MOCK 改成 false 即可，
 * 其余代码不用动（见 api/index.js）。
 */

export const USE_MOCK = true

/** 真实后端地址。走 vite.config.js 的 proxy 时留空字符串即可 */
export const API_BASE = '/api/v1'

/** 轮询参数。取自 docs/数据契约.md 第四节第 1 项的当前处理方式 */
export const POLL_INTERVAL_MS = 1500
export const POLL_MAX_ATTEMPTS = 60 // 90 秒

/** 轮询超过这个时长仍未结束时，提示"处理时间较长"，但不放弃等待 */
export const SLOW_POLL_MS = 90_000

/** 网络/服务端错误的重试参数：最多 3 次尝试，间隔 1s / 2s / 4s */
export const RETRY_MAX_ATTEMPTS = 3
export const RETRY_BASE_DELAY_MS = 1000
