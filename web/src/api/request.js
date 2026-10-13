/**
 * 请求层核心：单次请求截止、取消传播、自动重试与轮询循环。
 *
 * 与 index.js 的分工：这里不 import config.js（它依赖浏览器环境做 mock 解析），
 * base、超时、重试等参数全部由调用方注入，因此本模块可以在 node 里直接单测。
 */

// —— 统一的错误类型：页面按 kind 区分展示方式 ——

export class ApiError extends Error {
  constructor(message, { kind = 'SERVER', code = null, status = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind // NETWORK | PARSE | SERVER | TIMEOUT | CANCELED
    this.code = code
    this.status = status
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/**
 * 单次请求的应用层默认截止：30 秒。
 * fetch 本身没有超时，挂起的连接会拖死整个轮询循环，
 * 所以每一跳都要有明确截止，覆盖连接与响应体读取。
 */
export const REQUEST_TIMEOUT_MS = 30_000

/**
 * 单次请求。失败时抛 ApiError，kind 标出失败在哪一环。
 *
 * 取消语义：调用方 signal 与本地超时共用一个内部 AbortController，
 * 两者都会让 fetch / res.json() 在读体阶段也中断；
 * 主动取消归 CANCELED，本地截止归 TIMEOUT，互不混淆。
 */
export async function requestOnce(path, options = {}, { base = '', timeoutMs = REQUEST_TIMEOUT_MS, signal } = {}) {
  if (signal?.aborted) throw new ApiError('已取消', { kind: 'CANCELED' })

  const ctrl = new AbortController()
  const onExternalAbort = () => ctrl.abort()
  signal?.addEventListener('abort', onExternalAbort, { once: true })
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)

  /** 中断发生时按触发源归类：调用方取消优先于本地超时 */
  const abortError = () =>
    signal?.aborted
      ? new ApiError('已取消', { kind: 'CANCELED' })
      : new ApiError(`请求超过 ${Math.round(timeoutMs / 1000)} 秒未响应`, { kind: 'TIMEOUT' })

  try {
    let res
    try {
      res = await fetch(`${base}${path}`, { ...options, signal: ctrl.signal })
    } catch {
      // 中断（取消/超时）优先于连接错误归类；
      // 其余（直连不通、DNS 失败、CORS 被拦）归 NETWORK，
      // 明确区分于"后端返回了错误"，因为排查方向完全不同。
      if (ctrl.signal.aborted) throw abortError()
      throw new ApiError('无法连接后端，请确认服务已启动、代理配置正确', { kind: 'NETWORK' })
    }

    if (!res.ok) {
      // 契约要求失败返回非 2xx。这里读一下是否有结构化错误体。
      // 5xx 且没有契约错误体的，多半是代理/网关打不通上游（dev proxy 后端没启动、
      // 网关超时）时自己返回的错误页——根因是连接问题，归入 NETWORK，
      // 否则用户会拿着"服务端处理失败"去排查一个根本没收到请求的后端。
      let code = null
      let message = `请求失败（HTTP ${res.status}）`
      let hasContractError = false
      try {
        const body = await res.json()
        if (body?.error?.message) {
          message = body.error.message
          hasContractError = true
        }
        if (body?.error?.code) code = body.error.code
      } catch (e) {
        if (ctrl.signal.aborted) throw abortError()
        /* 错误体不是 JSON，用默认文案 */
      }
      if (res.status >= 500 && !hasContractError) {
        throw new ApiError('无法连接后端，请确认服务已启动、代理配置正确', {
          kind: 'NETWORK',
          code,
          status: res.status,
        })
      }
      throw new ApiError(message, { kind: 'SERVER', code, status: res.status })
    }

    try {
      return await res.json()
    } catch {
      if (ctrl.signal.aborted) throw abortError()
      throw new ApiError('后端返回的内容不是合法 JSON', { kind: 'PARSE', status: res.status })
    }
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', onExternalAbort)
  }
}

/**
 * 值得重试的失败：连接层错误（NETWORK）和服务端 5xx。
 * 这两类通常是瞬时的（冷启动、网关抖动）；
 * 4xx 是请求本身的问题，CANCELED / TIMEOUT 是明确的终止语义，重试无意义。
 */
export function isRetryable(e) {
  return e instanceof ApiError && (e.kind === 'NETWORK' || (e.kind === 'SERVER' && e.status >= 500))
}

/**
 * 带重试的请求。最多 retries 次尝试，间隔按 1s / 2s / 4s 指数退避。
 * onRetry 供页面显示"正在重试"之类的提示；signal 供取消。
 * 重试用尽后抛出最后一次的错误，页面按它的 kind 分类提示。
 */
export async function request(
  path,
  options = {},
  { base = '', timeoutMs = REQUEST_TIMEOUT_MS, retries = 3, baseDelayMs = 1000, onRetry, signal } = {}
) {
  let lastError
  for (let attempt = 1; attempt <= retries; attempt += 1) {
    if (signal?.aborted) throw new ApiError('已取消', { kind: 'CANCELED' })
    try {
      return await requestOnce(path, options, { base, timeoutMs, signal })
    } catch (e) {
      lastError = e
      const canRetry = isRetryable(e) && attempt < retries && !signal?.aborted
      if (!canRetry) throw e
      onRetry?.(attempt, retries, e)
      await sleep(baseDelayMs * 2 ** (attempt - 1))
    }
  }
  throw lastError
}

/**
 * 带上传进度回调的 POST。fetch 拿不到上传进度，这里用 XMLHttpRequest。
 * 错误分类与 request() 保持一致，页面不用区分两条路径。
 * 与 fetch 路径同样有应用层截止（xhr.timeout）与调用方取消（signal）。
 * @param {string} path
 * @param {FormData} form
 * @param {(percent: number) => void} onProgress 0-100，仅在可计算总长时回调
 */
export function requestWithUploadProgress(
  path,
  form,
  onProgress,
  { base = '', timeoutMs = REQUEST_TIMEOUT_MS, signal } = {}
) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new ApiError('已取消', { kind: 'CANCELED' }))
      return
    }
    const xhr = new XMLHttpRequest()

    const onAbort = () => {
      xhr.abort()
      reject(new ApiError('已取消', { kind: 'CANCELED' }))
    }
    /** 结束后摘掉取消监听，避免悬挂的监听器把已完成的请求再 reject 一次 */
    const cleanup = () => signal?.removeEventListener('abort', onAbort)
    const settle = (fn) => (value) => {
      cleanup()
      fn(value)
    }
    resolve = settle(resolve)
    reject = settle(reject)

    xhr.open('POST', `${base}${path}`)
    xhr.responseType = 'json'
    xhr.timeout = timeoutMs
    signal?.addEventListener('abort', onAbort, { once: true })

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const body = xhr.response
        if (body && typeof body === 'object') {
          resolve(body)
        } else {
          reject(new ApiError('后端返回的内容不是合法 JSON', { kind: 'PARSE', status: xhr.status }))
        }
        return
      }
      // 与 requestOnce 同一规则：5xx 且没有契约错误体的按连接问题归 NETWORK
      //（典型场景：dev proxy 的上游后端没启动，代理自己回了错误页）
      let code = null
      let message = `请求失败（HTTP ${xhr.status}）`
      let hasContractError = false
      const body = xhr.response
      if (body?.error?.message) {
        message = body.error.message
        hasContractError = true
      }
      if (body?.error?.code) code = body.error.code
      if (xhr.status >= 500 && !hasContractError) {
        reject(
          new ApiError('无法连接后端，请确认服务已启动、代理配置正确', {
            kind: 'NETWORK',
            code,
            status: xhr.status,
          })
        )
        return
      }
      reject(new ApiError(message, { kind: 'SERVER', code, status: xhr.status }))
    }

    xhr.onerror = () => {
      reject(new ApiError('无法连接后端，请确认服务已启动、代理配置正确', { kind: 'NETWORK' }))
    }

    xhr.ontimeout = () => {
      reject(new ApiError(`上传超过 ${Math.round(timeoutMs / 1000)} 秒未响应`, { kind: 'TIMEOUT' }))
    }

    xhr.send(form)
  })
}

/**
 * 轮询直到任务结束。
 *
 * 终止条件：拿到终态、达到轮询上限（硬截止）、调用方通过 signal 取消。
 * 超过 slowMs（软提示线，必须小于硬截止才轮得到）未结束时通过 onSlow
 * 提示"处理时间较长"，但继续等待——不把它当失败，让后端有机会跑完大文件。
 * 超时和失败都抛 ApiError，由页面决定怎么显示——绝不返回一个空结果，
 * 否则页面会把它渲染成"检查完成，没有问题"。
 *
 * fetchTask 由调用方提供（ mock / 真实请求的差异在 index.js 里收口）；
 * sleep / now 可注入，便于用虚拟时钟测试，不等真实的 90 秒。
 */
export async function pollTask(
  fetchTask,
  {
    onTick,
    onSlow,
    signal,
    intervalMs,
    maxAttempts,
    slowMs,
    sleep: sleepFn = sleep,
    now = () => Date.now(),
  }
) {
  const TERMINAL = ['COMPLETED', 'PARTIAL', 'FAILED']
  const startedAt = now()
  let slowNotified = false

  for (let i = 0; i < maxAttempts; i += 1) {
    if (signal?.aborted) throw new ApiError('已取消', { kind: 'CANCELED' })

    const task = await fetchTask()
    onTick?.(task)

    if (TERMINAL.includes(task.status)) return task

    if (!slowNotified && now() - startedAt > slowMs) {
      slowNotified = true
      onSlow?.()
    }

    await sleepFn(intervalMs)
  }

  throw new ApiError('处理时间过长，请稍后重试', { kind: 'TIMEOUT' })
}
