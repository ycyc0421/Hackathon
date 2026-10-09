/**
 * 前后端切换点。
 *
 * 开发期用 mock，后端就绪后把 USE_MOCK 改成 false 即可，
 * 其余代码不用动（见 api/index.js）。
 */

export const USE_MOCK = true

/** 真实后端地址。走 vite.config.js 的 proxy 时留空字符串即可 */
export const API_BASE = '/api/v1'

/** 轮询参数。取自 docs/数据契约.md 第四节第 1 项的默认做法 */
export const POLL_INTERVAL_MS = 1500
export const POLL_MAX_ATTEMPTS = 60 // 90 秒
