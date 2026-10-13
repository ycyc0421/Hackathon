/** 示例流程仅模拟状态推进，终态保持样例的业务结果与失败状态。 */
const RUN_MS = 9000
const starts = new Map()
let sequence = 0

function startedAt(taskId) {
  if (starts.has(taskId)) return starts.get(taskId)
  let time = Date.now()
  try {
    const key = 'app.mockTaskStartedAt:' + taskId
    const saved = Number(window.sessionStorage.getItem(key))
    if (Number.isFinite(saved) && saved > 0) time = saved
    else window.sessionStorage.setItem(key, String(time))
  } catch { /* 存储不可用时继续使用内存中的创建时刻 */ }
  starts.set(taskId, time)
  return time
}

export function startMockTask() {
  const id = 'mock_' + Date.now() + '_' + sequence++
  startedAt(id)
  return id
}

export function mockSnapshot(taskId, sample) {
  const start = startedAt(taskId)
  const ratio = Math.max(0, (Date.now() - start) / RUN_MS)
  const result = { ...sample, task_id: taskId, created_at: new Date(start).toISOString() }
  if (ratio >= 1) return { ...result, finished_at: new Date(start + RUN_MS).toISOString() }

  const pending = ratio < 0.12
  const documents = sample.documents ?? []
  const processed = Math.min(documents.length, Math.floor(Math.max(0, ratio - 0.12) / 0.68 * documents.length))
  return {
    ...result,
    status: pending ? 'PENDING' : 'PROCESSING',
    finished_at: null,
    documents: documents.map((doc, index) => ({
      ...doc,
      process_status: index < processed ? doc.process_status : !pending && index === processed ? 'PARSING' : 'UPLOADED',
      page_count: index < processed ? doc.page_count : null,
      error_message: index < processed ? doc.error_message : null,
    })),
    extractions: [], comparisons: [], risks: [], items: [], errors: [],
    summary: { document_count: documents.length, field_count: 0, conflict_count: 0, missing_count: 0, risk_count: 0, unrecognized_count: 0 },
  }
}
