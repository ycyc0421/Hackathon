/**
 * 数据访问层。页面只调这里的函数，不直接 fetch。
 *
 * mock 与真实实现共用同一组函数签名，切换只靠 config.js 的 USE_MOCK。
 * 这样后端就绪后，页面代码一行都不用改。
 *
 * 契约见 docs/数据契约.md 与 docs/schema/check-task.schema.json
 */

import {
  USE_MOCK,
  API_BASE,
  POLL_INTERVAL_MS,
  POLL_MAX_ATTEMPTS,
  RETRY_MAX_ATTEMPTS,
  RETRY_BASE_DELAY_MS,
  SLOW_POLL_MS,
} from './config.js'
import completedSample from '../mock/check-completed.json'
import partialSample from '../mock/check-partial.json'
import multiItemSample from '../mock/check-multi-item.json'
import cleanSample from '../mock/check-clean.json'

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

// —— mock 实现 ——

/**
 * mock 场景按 key 注册。演示时需要稳定重复同一场景，
 * 所以不能按提交次数轮换——由顶栏的场景选择器指定。
 */
const MOCK_SAMPLES = {
  'single-item': completedSample, // 单品名 · 1 处数量冲突
  'partial-fail': partialSample, // 单品名 · 一份文件处理失败
  'multi-item': multiItemSample, // 双品名 · 冲突/一致/不适用混合
  clean: cleanSample, // 全部一致 · 零风险
}

let mockScenario = 'single-item'

/** 指定 mock 场景。key 不存在时忽略，避免选择器外的调用把场景打坏 */
export function setMockScenario(key) {
  if (MOCK_SAMPLES[key]) mockScenario = key
}

/** 已注册的场景 key 列表，供选择器渲染选项 */
export function listMockScenarios() {
  return Object.keys(MOCK_SAMPLES)
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** 去掉示例数据里的说明性键，它不属于契约 */
function stripComment(obj) {
  const { _comment, ...rest } = obj
  return rest
}

/** 返回当前选定场景的深拷贝，调用方改 task_id 不会污染样例 */
function nextMockSample() {
  return stripComment(JSON.parse(JSON.stringify(MOCK_SAMPLES[mockScenario])))
}

// —— 真实实现 ——

/** 单次请求。失败时抛 ApiError，kind 标出失败在哪一环 */
async function requestOnce(path, options = {}) {
  let res
  try {
    res = await fetch(`${API_BASE}${path}`, options)
  } catch (e) {
    // 直连不通、DNS 失败、CORS 被拦都落这里。
    // 明确区分于"后端返回了错误"，因为排查方向完全不同。
    throw new ApiError('无法连接后端，请确认服务已启动、代理配置正确', { kind: 'NETWORK' })
  }

  if (!res.ok) {
    // 契约要求失败返回非 2xx。这里读一下是否有结构化错误体
    let code = null
    let message = `请求失败（HTTP ${res.status}）`
    try {
      const body = await res.json()
      if (body?.error?.message) message = body.error.message
      if (body?.error?.code) code = body.error.code
    } catch {
      /* 错误体不是 JSON，用默认文案 */
    }
    throw new ApiError(message, { kind: 'SERVER', code, status: res.status })
  }

  try {
    return await res.json()
  } catch {
    throw new ApiError('后端返回的内容不是合法 JSON', { kind: 'PARSE', status: res.status })
  }
}

/**
 * 值得重试的失败：连接层错误（NETWORK）和服务端 5xx。
 * 这两类通常是瞬时的（冷启动、网关抖动）；4xx 是请求本身的问题，重试无意义。
 */
function isRetryable(e) {
  return e instanceof ApiError && (e.kind === 'NETWORK' || (e.kind === 'SERVER' && e.status >= 500))
}

/**
 * 带重试的请求。最多 RETRY_MAX_ATTEMPTS 次尝试，间隔按 1s / 2s / 4s 指数退避。
 * onRetry 供页面显示"正在重试"之类的提示；signal 供取消。
 * 重试用尽后抛出最后一次的错误，页面按它的 kind 分类提示。
 */
async function request(path, options = {}, { onRetry, signal } = {}) {
  let lastError
  for (let attempt = 1; attempt <= RETRY_MAX_ATTEMPTS; attempt += 1) {
    if (signal?.aborted) throw new ApiError('已取消', { kind: 'CANCELED' })
    try {
      return await requestOnce(path, options)
    } catch (e) {
      lastError = e
      const canRetry = isRetryable(e) && attempt < RETRY_MAX_ATTEMPTS
      if (!canRetry) throw e
      onRetry?.(attempt, RETRY_MAX_ATTEMPTS, e)
      await sleep(RETRY_BASE_DELAY_MS * 2 ** (attempt - 1))
    }
  }
  throw lastError
}

/**
 * 带上传进度回调的 POST。fetch 拿不到上传进度，这里用 XMLHttpRequest。
 * 错误分类与 request() 保持一致，页面不用区分两条路径。
 * @param {string} path
 * @param {FormData} form
 * @param {(percent: number) => void} onProgress 0-100，仅在可计算总长时回调
 */
function requestWithUploadProgress(path, form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE}${path}`)
    xhr.responseType = 'json'

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
      let code = null
      let message = `请求失败（HTTP ${xhr.status}）`
      const body = xhr.response
      if (body?.error?.message) message = body.error.message
      if (body?.error?.code) code = body.error.code
      reject(new ApiError(message, { kind: 'SERVER', code, status: xhr.status }))
    }

    xhr.onerror = () => {
      reject(new ApiError('无法连接后端，请确认服务已启动、代理配置正确', { kind: 'NETWORK' }))
    }

    xhr.send(form)
  })
}

// —— 对外接口 ——

/**
 * 创建检查任务。契约第四节第 1 项按任务式设计。
 * @param {{ files: File[], destinationCountry: string, notes?: string }} input
 * @param {{ onUploadProgress?: (percent: number) => void, onRetry?: Function, signal?: AbortSignal }} [options]
 *        onUploadProgress 收到 0-100 的整数百分比，仅在能计算总长时回调（走 XHR，无重试）
 * @returns {Promise<{ task_id: string, status: string }>}
 */
export async function createCheck(
  { files, destinationCountry, notes },
  { onUploadProgress, onRetry, signal } = {}
) {
  if (USE_MOCK) {
    // mock 下按文件大小模拟上传进度，让上传页能看到真实的进度条形态
    const total = files.reduce((s, f) => s + f.size, 0) || 1
    let loaded = 0
    for (const f of files) {
      await sleep(150)
      loaded += f.size
      onUploadProgress?.(Math.round((loaded / total) * 100))
    }
    return {
      task_id: `mock_${Date.now()}`,
      status: 'PENDING',
      created_at: new Date().toISOString(),
    }
  }

  const form = new FormData()
  for (const f of files) form.append('files', f)
  form.append('destination_country', destinationCountry)
  if (notes) form.append('notes', notes)

  if (onUploadProgress) {
    return requestWithUploadProgress('/checks', form, onUploadProgress)
  }
  return request('/checks', { method: 'POST', body: form }, { onRetry, signal })
}

/**
 * 查询任务状态与结果。取一次结果用这个；轮询请用 pollCheck。
 * @returns {Promise<object>} CheckTask
 */
export async function getCheck(taskId, { onRetry, signal } = {}) {
  if (USE_MOCK) {
    await sleep(500)
    const sample = nextMockSample()
    sample.task_id = taskId
    return sample
  }
  return request(`/checks/${encodeURIComponent(taskId)}`, {}, { onRetry, signal })
}

/**
 * 轮询直到任务结束。
 *
 * 终止条件：拿到终态、达到轮询上限、调用方通过 signal 取消。
 * 超过 SLOW_POLL_MS（90 秒）未结束时通过 onSlow 提示"处理时间较长"，
 * 但继续等待——不把它当失败，让后端有机会跑完大文件。
 * 超时和失败都抛 ApiError，由页面决定怎么显示——绝不返回一个空结果，
 * 否则页面会把它渲染成"检查完成，没有问题"。
 *
 * @param {string} taskId
 * @param {{ onTick?: (task: object) => void, onSlow?: () => void, onRetry?: Function, signal?: AbortSignal }} options
 */
export async function pollCheck(taskId, { onTick, onSlow, onRetry, signal } = {}) {
  const TERMINAL = ['COMPLETED', 'PARTIAL', 'FAILED']
  const startedAt = Date.now()
  let slowNotified = false

  for (let i = 0; i < POLL_MAX_ATTEMPTS; i += 1) {
    if (signal?.aborted) throw new ApiError('已取消', { kind: 'CANCELED' })

    // mock 下没有真实后端，直接走 getCheck 的 mock 分支拿样例；
    // 否则请求会打到 dev server 的 SPA 回退上，拿到 HTML 报 PARSE 错误
    const task = USE_MOCK
      ? await getCheck(taskId, { signal })
      : await request(`/checks/${encodeURIComponent(taskId)}`, {}, { onRetry, signal })
    onTick?.(task)

    if (TERMINAL.includes(task.status)) return task

    if (!slowNotified && Date.now() - startedAt > SLOW_POLL_MS) {
      slowNotified = true
      onSlow?.()
    }

    await sleep(USE_MOCK ? 300 : POLL_INTERVAL_MS)
  }

  throw new ApiError('处理时间过长，请稍后重试', { kind: 'TIMEOUT' })
}

/**
 * 评测结果。契约第四节第 10 项未定，拿不到就给 NOT_RUN。
 * 页面据此显示"尚未评测"，不填任何数字。
 */
export async function getEvaluation(options = {}) {
  if (USE_MOCK) {
    await sleep(200)
    return {
      status: 'NOT_RUN',
      dataset_version: null,
      sample_count: 0,
      model_version: null,
      metrics: null,
      error_breakdown: null,
      run_at: null,
    }
  }

  try {
    return await request('/evaluation/latest', {}, options)
  } catch (e) {
    // 接口还没做属于预期内。降级为"尚未评测"，但把原因留着便于排查
    if (e.status === 404) {
      return {
        status: 'NOT_RUN',
        dataset_version: null,
        sample_count: 0,
        model_version: null,
        metrics: null,
        error_breakdown: null,
        run_at: null,
      }
    }
    throw e
  }
}

/** 上传前的前端校验。上限来自契约第四节第 11 项的当前处理方式，需后端侧确认 */
export const UPLOAD_LIMITS = {
  maxFiles: 10,
  maxFileSizeMB: 20,
  accept: '.pdf,.png,.jpg,.jpeg,.webp',
}

export function validateFiles(fileList) {
  const errors = []
  const files = Array.from(fileList)

  if (files.length === 0) errors.push('请至少选择一份文件')
  if (files.length > UPLOAD_LIMITS.maxFiles) {
    errors.push(`一次最多 ${UPLOAD_LIMITS.maxFiles} 份文件，当前 ${files.length} 份`)
  }

  for (const f of files) {
    const mb = f.size / 1024 / 1024
    if (mb > UPLOAD_LIMITS.maxFileSizeMB) {
      errors.push(`${f.name} 超过 ${UPLOAD_LIMITS.maxFileSizeMB}MB（${mb.toFixed(1)}MB）`)
    }
  }

  return errors
}

export { USE_MOCK }
