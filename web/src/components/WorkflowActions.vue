<script setup>
/**
 * 报告导出与人工修正。
 *
 * 网络行为全部收口在 api/index.js（getCorrections / createCorrection /
 * getReportContent / exportReportArchive），本组件只处理：字段选择、修正值与
 * 原因输入、busy、提示与文件下载交互——不直接 fetch、不 import request 层。
 *
 * 导出有两条出口，对应报告契约 v2 的两种视图（issue #51）：
 * - **HTML 报告**：拉 `view=content`，由 `src/report/document.js` 在前端排成
 *   一份自包含的文档再下载。后端 `format=html` 已返回 410，排版是前端的职责。
 * - **归档 JSON**：拉 `view=archive` 的原始文件，保留完整抽取结构与审计
 *   before/after。默认报告正文不含这些内容，所以必须留一个能拿到它的出口，
 *   否则完整证据就没有访问路径了。
 *
 * 关键语义（见交付说明 F2）：
 * - source_hash 来自 GET corrections 的 result_hash，不对公开 getCheck JSON 自算；
 * - 同一次修正的网络重试复用同一 request_id 与载荷（幂等）；修改选择/值/原因或
 *   切换源任务后才作废旧载荷、生成新标识；
 * - 冲突（409）提示重新读取上下文，不悄悄改 hash 后自动重提；
 * - 成功采用返回的子任务，原任务与原始证据保留，不自行改 comparisons/summary；
 * - 处理中切换任务时，过期的响应不覆盖新任务。
 */
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { isMock, getCorrections, createCorrection, getReportContent, exportReportArchive } from '../api/index.js'
import { buildReportHtml, reportFileName } from '../report/document.js'

const task = inject('task')
const taskError = inject('taskError', null)

/** 可修正的整票字段白名单（文档级，line_no 为空） */
const documentKeys = new Set(['packages','gross_weight','net_weight','volume','quantity','hs_code','total_amount','currency','description','document_no','invoice_no','shipment_date','bill_of_lading_no','contract_no','container_no','shipper','consignee','port_of_loading','port_of_discharge'])
/** 可修正的商品级字段白名单（line_no 有值） */
const itemKeys = new Set(['item_code','description','hs_code','quantity','packages','net_weight','gross_weight','volume','unit_price','amount'])

const busy = ref(false)
const error = ref('')
const message = ref('')
const selection = ref('')
const value = ref('')
const reason = ref('')

/**
 * 待提交的修正载荷 { request_id, source_hash, reason, changes }。
 * 首次提交时构建一次；网络重试复用它保证幂等。任何输入变化或切任务都会
 * 置 null，下次提交重新读取 result_hash 并生成新 request_id。
 */
let pending = null
let activeRequest = null
onBeforeUnmount(() => activeRequest?.abort())

const terminal = computed(() => ['COMPLETED','PARTIAL','FAILED'].includes(task.value?.status))
/** 可导出：真实后端、已到终态、当前任务没有请求错误。mock/未结束不发真实请求 */
const available = computed(() => !isMock() && terminal.value && !taskError?.value)
/** 可修正：COMPLETED/PARTIAL；FAILED 终态可导出失败明细但不可修正 */
const editable = computed(() => available.value && ['COMPLETED','PARTIAL'].includes(task.value?.status))

/** 候选字段：已抽取文件中、属于修正白名单的字段；商品行带行号，整票字段不带 */
const options = computed(() => {
  const files = new Map((task.value?.documents || []).filter(d => d.process_status === 'EXTRACTED').map(d => [d.file_id,d.file_name]))
  return (task.value?.extractions || []).flatMap(e => e.fields.filter(f => files.has(e.file_id) && (f.line_no != null ? itemKeys : documentKeys).has(f.field_key)).map(f => ({
    id: `${e.file_id}:${f.line_no ?? 'document'}:${f.field_key}`,
    file_id: e.file_id, item_no: f.line_no ?? null, field_key: f.field_key,
    label: `${files.get(e.file_id)} · ${f.line_no != null ? `第 ${f.line_no} 行 · ` : ''}${f.label}`,
    field: f,
  })))
})
const chosen = computed(() => options.value.find(o => o.id === selection.value))

/** 输入变化 → 作废旧载荷，下次提交重新读取上下文与新 request_id */
watch([selection,value,reason], () => { pending = null })
/** 切换任务 → 清空选择、错误与成功提示，避免旧状态串到新任务 */
watch(() => task.value?.task_id, () => {
  activeRequest?.abort()
  selection.value = ''; value.value = ''; reason.value = ''; pending = null; error.value = ''; message.value = ''
}, { flush: 'sync' })

async function revise() {
  if (!editable.value || !chosen.value || !value.value.trim() || !reason.value.trim() || busy.value) return
  busy.value = true; error.value = ''; message.value = ''
  const sourceId = task.value.task_id
  const change = { file_id: chosen.value.file_id, item_no: chosen.value.item_no, field_key: chosen.value.field_key, value: value.value }
  const submittedReason = reason.value
  const controller = new AbortController()
  activeRequest = controller
  try {
    if (!pending) {
      const source = await getCorrections(sourceId, { signal: controller.signal })
      if (controller.signal.aborted || task.value?.task_id !== sourceId) return
      pending = {
        request_id: crypto.randomUUID(),
        source_hash: source.result_hash,
        reason: submittedReason,
        changes: [change],
      }
    }
    const child = await createCorrection(sourceId, pending, { signal: controller.signal })
    // 竞态守卫：提交期间若已切到别的任务，丢弃过期响应，不覆盖新任务
    if (controller.signal.aborted || task.value?.task_id !== sourceId) return
    task.value = child
    message.value = '已创建修正任务并重算。原任务和原始证据保留，报告包含修正审计。'
    // 成功后旧载荷已消费，下一次修改会重新读取上下文
    pending = null
    selection.value = ''; value.value = ''; reason.value = ''
  } catch (e) {
    if (controller.signal.aborted || task.value?.task_id !== sourceId) return
    // 冲突：源结果已变化，旧 source_hash 失效，必须重新读取上下文后再提交
    if (e?.status === 409) pending = null
    error.value = e?.status === 409
      ? '修正上下文冲突，请刷新任务并核对内容后重新提交。'
      : (e?.message || '修正失败，请重试')
  } finally { activeRequest = null; busy.value = false }
}

/** 触发浏览器下载。Blob 用完即释放，避免长时间占着内存 */
function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url; anchor.download = filename; anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/**
 * 导出 HTML 报告。
 *
 * 两步：先取结构化内容，再在前端排成文档。**排版失败不下载半成品**——
 * 宁可报错也不给一份内容不全的报告，那比没有报告更危险。
 */
async function downloadHtml() {
  if (!available.value || busy.value) return
  busy.value = true; error.value = ''; message.value = ''
  const id = task.value.task_id
  const controller = new AbortController()
  activeRequest = controller
  try {
    const content = await getReportContent(id, { view: 'content', signal: controller.signal })
    if (controller.signal.aborted || task.value?.task_id !== id) return
    const html = buildReportHtml(content)
    saveBlob(new Blob([html], { type: 'text/html;charset=utf-8' }), reportFileName(content, 'html'))
    message.value = '已导出 HTML 报告。可在浏览器中打开，或用「打印 → 另存为 PDF」留档。'
  } catch (e) {
    if (controller.signal.aborted || task.value?.task_id !== id) return
    error.value = e?.message || '导出失败'
  } finally { activeRequest = null; busy.value = false }
}

/** 导出归档 JSON（完整抽取结构与审计记录） */
async function downloadArchive() {
  if (!available.value || busy.value) return
  busy.value = true; error.value = ''; message.value = ''
  const id = task.value.task_id
  const controller = new AbortController()
  activeRequest = controller
  try {
    const blob = await exportReportArchive(id, { signal: controller.signal })
    if (controller.signal.aborted || task.value?.task_id !== id) return
    saveBlob(blob, `report-${id}-archive.json`)
    message.value = '已导出归档 JSON，包含完整抽取结构与修正审计，供离线核对。'
  } catch (e) {
    if (controller.signal.aborted || task.value?.task_id !== id) return
    // 任何失败都不下载错误内容、不显示成功
    error.value = e?.message || '导出失败'
  } finally { activeRequest = null; busy.value = false }
}
</script>

<template>
  <section class="card workflow-actions">
    <h2 class="card-title">报告导出与人工修正</h2>
    <p v-if="isMock()">示例任务不支持服务端导出或修正。请切换真实后端并上传单证。</p>
    <template v-else>
      <p>处理完成不代表合规通过。报告包含原始证据、警告、未检查项和修正记录；HTML 报告可在浏览器打印为 PDF。</p>
      <div class="workflow-buttons">
        <button :disabled="!available || busy" @click="downloadHtml">导出 HTML 报告</button>
        <button :disabled="!available || busy" @click="downloadArchive">导出归档 JSON</button>
      </div>
      <p class="workflow-hint">归档 JSON 保留完整抽取结构与修正审计，供离线核对；默认报告正文不含这些明细。</p>
      <form v-if="editable" @submit.prevent="revise">
        <p>修正有效抽取值后重新比对，不重跑 OCR。原始读数保持不变；当前署名为未认证操作者。</p>
        <label>选择已有字段
          <select v-model="selection" :disabled="busy" required>
            <option value="">请选择文件与字段</option>
            <option v-for="option in options" :key="option.id" :value="option.id">{{ option.label }}</option>
          </select>
        </label>
        <p v-if="chosen">原始读数：{{ chosen.field.raw_value ?? '未读取' }}；当前有效值：{{ chosen.field.normalized_value ?? '未归一' }} {{ chosen.field.unit ?? '' }}</p>
        <label>修正值<input v-model="value" :disabled="busy" maxlength="2000" required placeholder="数值可带原单位；金额仅填数字，币种单独修改" /></label>
        <label>修正原因<textarea v-model="reason" :disabled="busy" maxlength="1000" required placeholder="说明核对的原件与修改依据" /></label>
        <button type="submit" :disabled="busy || !chosen || !value.trim() || !reason.trim()">{{ busy ? '正在处理…' : '保存修正并重算' }}</button>
      </form>
      <p v-else-if="!terminal">任务结束后可导出报告并修正字段。</p>
      <p v-else-if="task?.status === 'FAILED'">检查失败的任务不可修正，但可导出失败明细留档。</p>
    </template>
    <p v-if="error" role="alert" class="workflow-error">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
  </section>
</template>

<style scoped>
.workflow-actions p { margin: 12px 0; line-height: 1.6; }
.workflow-buttons { display: flex; gap: 12px; flex-wrap: wrap; }
/* 两个出口的区别要说清楚，否则用户不知道该点哪个 */
.workflow-hint { margin-top: 8px; color: var(--text-muted); font-size: var(--text-xs); }
form { display: grid; gap: 12px; margin-top: 20px; }
label { display: grid; gap: 6px; }
input, select, textarea { font: inherit; width: 100%; box-sizing: border-box; padding: 10px; border: 1px solid #bbb; border-radius: 6px; background: var(--surface, white); color: inherit; }
button { font: inherit; padding: 10px 16px; border: 1px solid #888; border-radius: 6px; cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
.workflow-error { color: #b42318; }
</style>
