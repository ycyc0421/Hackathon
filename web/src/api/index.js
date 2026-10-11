/**
 * 数据访问层。页面只调这里的函数，不直接 fetch。
 *
 * mock 与真实实现共用同一组函数签名，运行时切换靠 config.js 的 isMock()。
 * 这样后端就绪后，页面代码一行都不用改。
 *
 * 契约见 docs/数据契约.md 与 docs/schema/check-task.schema.json
 */

import {
  isMock,
  API_BASE,
  POLL_INTERVAL_MS,
  POLL_MAX_ATTEMPTS,
  RETRY_MAX_ATTEMPTS,
  RETRY_BASE_DELAY_MS,
  SLOW_POLL_MS,
  REQUEST_TIMEOUT_MS,
} from './config.js'
import {
  ApiError,
  request,
  requestWithUploadProgress,
  pollTask,
} from './request.js'
import { UPLOAD_LIMITS, validateFiles, splitByName } from './uploadLimits.js'
import completedSample from '../mock/check-completed.json'
import partialSample from '../mock/check-partial.json'
import multiItemSample from '../mock/check-multi-item.json'
import cleanSample from '../mock/check-clean.json'
import evaluationDoneSample from '../mock/evaluation-done.json'

// 错误类型、上传校验与同名拆分在此处统一出口，页面只从 api/index.js 引入
export { ApiError, UPLOAD_LIMITS, validateFiles, splitByName }

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

/**
 * 请求层（单次截止、取消传播、重试、上传进度、轮询循环）在 api/request.js，
 * 这里只负责把 config 的参数接上，保持对外函数签名不变。
 */

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
  if (isMock()) {
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
    return requestWithUploadProgress('/checks', form, onUploadProgress, {
      base: API_BASE,
      timeoutMs: REQUEST_TIMEOUT_MS,
      signal,
    })
  }
  return request(
    '/checks',
    { method: 'POST', body: form },
    { base: API_BASE, timeoutMs: REQUEST_TIMEOUT_MS, retries: RETRY_MAX_ATTEMPTS, baseDelayMs: RETRY_BASE_DELAY_MS, onRetry, signal }
  )
}

/**
 * 查询任务状态与结果。取一次结果用这个；轮询请用 pollCheck。
 * @returns {Promise<object>} CheckTask
 */
export async function getCheck(taskId, { onRetry, signal } = {}) {
  if (isMock()) {
    await sleep(500)
    const sample = nextMockSample()
    sample.task_id = taskId
    return sample
  }
  return request(
    `/checks/${encodeURIComponent(taskId)}`,
    {},
    { base: API_BASE, timeoutMs: REQUEST_TIMEOUT_MS, retries: RETRY_MAX_ATTEMPTS, baseDelayMs: RETRY_BASE_DELAY_MS, onRetry, signal }
  )
}

/**
 * 轮询直到任务结束。
 *
 * 终止条件：拿到终态、达到轮询上限（硬截止 90 秒）、调用方通过 signal 取消。
 * 超过 SLOW_POLL_MS（软提示线，30 秒，先于硬截止触发）未结束时通过 onSlow
 * 提示"处理时间较长"，但继续等待——不把它当失败，让后端有机会跑完大文件。
 * 超时和失败都抛 ApiError，由页面决定怎么显示——绝不返回一个空结果，
 * 否则页面会把它渲染成"检查完成，没有问题"。
 *
 * @param {string} taskId
 * @param {{ onTick?: (task: object) => void, onSlow?: () => void, onRetry?: Function, signal?: AbortSignal }} options
 */
export async function pollCheck(taskId, { onTick, onSlow, onRetry, signal } = {}) {
  // mock 下没有真实后端，直接走 getCheck 的 mock 分支拿样例；
  // 否则请求会打到 dev server 的 SPA 回退上，拿到 HTML 报 PARSE 错误
  const mock = isMock()
  const fetchTask = () =>
    mock
      ? getCheck(taskId, { signal })
      : request(
          `/checks/${encodeURIComponent(taskId)}`,
          {},
          { base: API_BASE, timeoutMs: REQUEST_TIMEOUT_MS, retries: RETRY_MAX_ATTEMPTS, baseDelayMs: RETRY_BASE_DELAY_MS, onRetry, signal }
        )

  return pollTask(fetchTask, {
    onTick,
    onSlow,
    signal,
    intervalMs: mock ? 300 : POLL_INTERVAL_MS,
    maxAttempts: POLL_MAX_ATTEMPTS,
    slowMs: SLOW_POLL_MS,
  })
}

/**
 * 评测结果。契约第四节第 10 项未定，拿不到就给 NOT_RUN。
 * 页面据此显示"尚未评测"，不填任何数字。
 * mock 下返回一份 DONE 示例（web/src/mock/evaluation-done.json），
 * 用于演示评测看板有数据时的形态，页面带有「示例数据」标识。
 */
export async function getEvaluation(options = {}) {
  if (isMock()) {
    await sleep(200)
    return stripComment(JSON.parse(JSON.stringify(evaluationDoneSample)))
  }

  try {
    return await request('/evaluation/latest', {}, {
      base: API_BASE,
      timeoutMs: REQUEST_TIMEOUT_MS,
      retries: RETRY_MAX_ATTEMPTS,
      baseDelayMs: RETRY_BASE_DELAY_MS,
      ...options,
    })
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

export { isMock }
