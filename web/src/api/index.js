/**
 * 数据访问层。页面只调这里的函数，不直接 fetch。
 *
 * mock 与真实实现共用同一组函数签名，切换只靠 config.js 的 USE_MOCK。
 * 这样后端就绪后，页面代码一行都不用改。
 *
 * 契约见 docs/数据契约.md 与 docs/schema/check-task.schema.json
 */

import { USE_MOCK, API_BASE, POLL_INTERVAL_MS, POLL_MAX_ATTEMPTS } from './config.js'
import completedSample from '../mock/check-completed.json'
import partialSample from '../mock/check-partial.json'

// —— 统一的错误类型：页面按 kind 区分展示方式 ——

export class ApiError extends Error {
  constructor(message, { kind = 'SERVER', code = null, status = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind // NETWORK | PARSE | SERVER | TIMEOUT
    this.code = code
    this.status = status
  }
}

// —— mock 实现 ——

const MOCK_SAMPLES = [completedSample, partialSample]
let mockRunCount = 0

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** 去掉示例数据里的说明性键，它不属于契约 */
function stripComment(obj) {
  const { _comment, ...rest } = obj
  return rest
}

/**
 * mock 依次返回两个样例，便于演示"正常路径"和"异常路径"两种状态。
 * 第一次跑查 completed，第二次跑查 partial，之后循环。
 */
function nextMockSample() {
  const sample = MOCK_SAMPLES[mockRunCount % MOCK_SAMPLES.length]
  mockRunCount += 1
  return stripComment(JSON.parse(JSON.stringify(sample)))
}

// —— 真实实现 ——

async function request(path, options = {}) {
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

// —— 对外接口 ——

/**
 * 创建检查任务。契约第四节第 1 项按任务式设计。
 * @param {{ files: File[], destinationCountry: string, notes?: string }} input
 * @returns {Promise<{ task_id: string, status: string }>}
 */
export async function createCheck({ files, destinationCountry, notes }) {
  if (USE_MOCK) {
    await sleep(400)
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

  return request('/checks', { method: 'POST', body: form })
}

/**
 * 查询任务状态与结果。轮询与取最终结果共用这一个接口。
 * @returns {Promise<object>} CheckTask
 */
export async function getCheck(taskId) {
  if (USE_MOCK) {
    await sleep(500)
    const sample = nextMockSample()
    sample.task_id = taskId
    return sample
  }
  return request(`/checks/${encodeURIComponent(taskId)}`)
}

/**
 * 轮询直到任务结束。
 *
 * 三个终止条件：拿到终态、超时、调用方通过 signal 取消。
 * 超时和失败都抛 ApiError，由页面决定怎么显示——绝不返回一个空结果，
 * 否则页面会把它渲染成"检查完成，没有问题"。
 *
 * @param {string} taskId
 * @param {{ onTick?: (task: object) => void, signal?: AbortSignal }} options
 */
export async function pollCheck(taskId, { onTick, signal } = {}) {
  const TERMINAL = ['COMPLETED', 'PARTIAL', 'FAILED']

  for (let i = 0; i < POLL_MAX_ATTEMPTS; i += 1) {
    if (signal?.aborted) throw new ApiError('已取消', { kind: 'TIMEOUT' })

    const task = await getCheck(taskId)
    onTick?.(task)

    if (TERMINAL.includes(task.status)) return task

    await sleep(USE_MOCK ? 300 : POLL_INTERVAL_MS)
  }

  throw new ApiError('处理时间过长，请稍后重试', { kind: 'TIMEOUT' })
}

/**
 * 评测结果。契约第四节第 10 项未定，拿不到就给 NOT_RUN。
 * 页面据此显示"尚未评测"，不填任何数字。
 */
export async function getEvaluation() {
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
    return await request('/evaluation/latest')
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

/** 上传前的前端校验。上限来自契约第四节第 11 项的默认值，需 F 确认 */
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
