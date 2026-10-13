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
  requestBlob,
  requestWithUploadProgress,
  pollTask,
} from './request.js'
import { UPLOAD_LIMITS, validateFiles, splitByName, isEdiName } from './uploadLimits.js'
import completedSample from '../mock/check-completed.json'
import partialSample from '../mock/check-partial.json'
import multiItemSample from '../mock/check-multi-item.json'
import cleanSample from '../mock/check-clean.json'
import evaluationDoneSample from '../mock/evaluation-done.json'
// EDI 合成场景夹具（issue #40）：手工构造的 API 形状数据，非真实接口输出，
// input.notes 中保留了合成标识。注册进示例体系供页面验收，不表示后端已解析 EDI。
import ediOnlySample from '../mock/check-edi-only.json'
import ediMixedSample from '../mock/check-edi-mixed.json'
import ediMultiItemSample from '../mock/check-edi-multi-item.json'
import ediPartialSample from '../mock/check-edi-partial.json'
import ediUnsupportedSample from '../mock/check-edi-unsupported.json'
import ediFailedSample from '../mock/check-edi-failed.json'

// 错误类型、上传校验、同名拆分与 EDI 识别在此处统一出口，页面只从 api/index.js 引入
export { ApiError, UPLOAD_LIMITS, validateFiles, splitByName, isEdiName }

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
  'edi-only': ediOnlySample, // EDI · 单份报文（0 冲突不等于通过）
  'edi-mixed': ediMixedSample, // EDI + PDF + 图片 · 数量冲突
  'edi-multi-item': ediMultiItemSample, // EDI · 双商品顺序与缺失
  'edi-partial': ediPartialSample, // EDI · 有效 + 截断并存
  'edi-unsupported': ediUnsupportedSample, // EDI · 后端不支持（整票失败）
  'edi-failed': ediFailedSample, // EDI · 报文截断解析失败
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
 * 终止条件：拿到终态、达到轮询上限（30 分钟）、调用方通过 signal 取消。
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

/**
 * 读取人工修正上下文。
 *
 * 返回 { task_id, result_hash, corrections }。result_hash 由后端按其内部存储
 * 结果计算，提交修正时原样回传作 source_hash——前端不对 getCheck 的公开扁平
 * JSON 自算 hash。mock 下没有真实后端存储，明确抛出不支持。
 *
 * @returns {Promise<{ task_id: string, result_hash: string, corrections: Array }>}
 */
export async function getCorrections(taskId, { signal } = {}) {
  if (isMock()) {
    throw new ApiError('示例任务不支持读取修正上下文，请切换真实后端', { kind: 'SERVER', code: 'MOCK_UNSUPPORTED' })
  }
  return request(
    `/checks/${encodeURIComponent(taskId)}/corrections`,
    {},
    { base: API_BASE, timeoutMs: REQUEST_TIMEOUT_MS, retries: RETRY_MAX_ATTEMPTS, baseDelayMs: RETRY_BASE_DELAY_MS, signal }
  )
}

/**
 * 提交人工修正并返回重算后的子任务（CheckTask）。
 *
 * payload 为 { request_id, source_hash, reason, changes }：
 * - source_hash 必须来自 getCorrections 的 result_hash；
 * - 同一次修正的网络重试复用相同 request_id 与载荷（幂等），修改选择/值/原因
 *   或源任务后才由调用方生成新标识；
 * - 成功返回子任务，原任务与原始证据保留，前端不自行改 comparisons/summary。
 *
 * 失败按真实返回呈现：404（任务不存在）、409（source_hash 冲突，应重新读取
 * 上下文）、422（修正值非法）等，不显示保存成功。
 *
 * @returns {Promise<object>} 子任务 CheckTask
 */
export async function createCorrection(taskId, payload, { signal } = {}) {
  if (isMock()) {
    throw new ApiError('示例任务不支持人工修正，请切换真实后端', { kind: 'SERVER', code: 'MOCK_UNSUPPORTED' })
  }
  // 修正是写操作，重试语义由调用方凭 request_id 幂等保证，这里不做网络层自动重试，
  // 避免同一 payload 被自动重发时与手动重试叠加出意料外的请求
  return request(
    `/checks/${encodeURIComponent(taskId)}/corrections`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    { base: API_BASE, timeoutMs: REQUEST_TIMEOUT_MS, retries: 1, signal }
  )
}

/**
 * 读取报告内容（报告契约 v2）。
 *
 * `GET /checks/{id}/report?format=json&view=content` 是默认视图：后端给出
 * 结构化内容，前端负责排版与呈现（issue #51）。`view='archive'` 返回完整的
 * 内部抽取结构与审计 before/after，用于归档留底，不进报告正文。
 *
 * 适用于 COMPLETED / PARTIAL / FAILED；处理中返回 409/TASK_NOT_FINISHED，
 * 不存在返回 404/TASK_NOT_FOUND，均按真实返回抛错。
 *
 * 注意：后端的 `format=html` 已返回 410/REPORT_PRESENTATION_MOVED，
 * 导出的 HTML 由前端 `src/report/document.js` 依据这里的内容生成。
 *
 * @param {'content'|'archive'} [view]
 * @returns {Promise<object>} report_version=2 的报告内容
 */
export async function getReportContent(taskId, { view = 'content', signal } = {}) {
  if (isMock()) {
    throw new ApiError('示例任务不支持服务端导出，请切换真实后端', { kind: 'SERVER', code: 'MOCK_UNSUPPORTED' })
  }
  const v = view === 'archive' ? 'archive' : 'content'
  return request(
    `/checks/${encodeURIComponent(taskId)}/report?format=json&view=${v}`,
    {},
    { base: API_BASE, timeoutMs: REQUEST_TIMEOUT_MS, retries: RETRY_MAX_ATTEMPTS, baseDelayMs: RETRY_BASE_DELAY_MS, signal }
  )
}

/**
 * 导出报告为 JSON 文件（归档视图）。
 *
 * 这是**归档**出口：完整抽取结构、原始字段值与审计 before/after 都在里面，
 * 供留底与离线核对。默认报告正文不含这些内容，所以要有一个地方能拿到。
 * 返回 Blob，文件名由组件生成；失败按真实返回抛错，绝不把错误响应当文件下载。
 *
 * @returns {Promise<Blob>}
 */
export async function exportReportArchive(taskId, { signal } = {}) {
  if (isMock()) {
    throw new ApiError('示例任务不支持服务端导出，请切换真实后端', { kind: 'SERVER', code: 'MOCK_UNSUPPORTED' })
  }
  return requestBlob(
    `/checks/${encodeURIComponent(taskId)}/report?format=json&view=archive`,
    {},
    { base: API_BASE, timeoutMs: REQUEST_TIMEOUT_MS, signal }
  )
}

export { isMock }
