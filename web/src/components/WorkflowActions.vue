<script setup>
/**
 * 报告导出与人工修正。
 *
 * 网络行为全部收口在 api/index.js（getCorrections / createCorrection / exportReport），
 * 本组件只处理：字段选择、修正值与原因输入、busy、提示与文件下载交互——不直接
 * fetch、不 import request 层。
 *
 * 关键语义（见交付说明 F2）：
 * - source_hash 来自 GET corrections 的 result_hash，不对公开 getCheck JSON 自算；
 * - 同一次修正的网络重试复用同一 request_id 与载荷（幂等）；修改选择/值/原因或
 *   切换源任务后才作废旧载荷、生成新标识；
 * - 冲突（409）提示重新读取上下文，不悄悄改 hash 后自动重提；
 * - 成功采用返回的子任务，原任务与原始证据保留，不自行改 comparisons/summary；
 * - 处理中切换任务时，过期的响应不覆盖新任务。
 */
import { computed, inject, ref, watch } from 'vue'
import { isMock, getCorrections, createCorrection, exportReport } from '../api/index.js'

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
watch(() => task.value?.task_id, () => { selection.value = ''; value.value = ''; reason.value = ''; pending = null; error.value = ''; message.value = '' })

async function revise() {
  if (!editable.value || !chosen.value || !value.value.trim() || !reason.value.trim() || busy.value) return
  busy.value = true; error.value = ''; message.value = ''
  const sourceId = task.value.task_id
  try {
    if (!pending) {
      const source = await getCorrections(sourceId)
      pending = {
        request_id: crypto.randomUUID(),
        source_hash: source.result_hash,
        reason: reason.value,
        changes: [{ file_id: chosen.value.file_id, item_no: chosen.value.item_no, field_key: chosen.value.field_key, value: value.value }],
      }
    }
    const child = await createCorrection(sourceId, pending)
    // 竞态守卫：提交期间若已切到别的任务，丢弃过期响应，不覆盖新任务
    if (task.value?.task_id !== sourceId) return
    task.value = child
    message.value = '已创建修正任务并重算。原任务和原始证据保留，报告包含修正审计。'
    // 成功后旧载荷已消费，下一次修改会重新读取上下文
    pending = null
    selection.value = ''; value.value = ''; reason.value = ''
  } catch (e) {
    if (task.value?.task_id !== sourceId) return
    // 冲突：源结果已变化，旧 source_hash 失效，必须重新读取上下文后再提交
    error.value = e?.status === 409
      ? '源任务结果已变化，请重新读取后再提交修正。'
      : (e?.message || '修正失败，请重试')
  } finally { busy.value = false }
}

async function download(format) {
  if (!available.value || busy.value) return
  busy.value = true; error.value = ''
  const id = task.value.task_id
  try {
    const blob = await exportReport(id, format)
    if (task.value?.task_id !== id) return
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url; anchor.download = `report-${id}.${format}`; anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) {
    if (task.value?.task_id !== id) return
    // 任何失败都不下载错误内容、不显示成功
    error.value = e?.message || '导出失败'
  } finally { busy.value = false }
}
</script>

<template>
  <section class="card workflow-actions">
    <h2 class="card-title">报告导出与人工修正</h2>
    <p v-if="isMock()">示例任务不支持服务端导出或修正。请切换真实后端并上传单证。</p>
    <template v-else>
      <p>处理完成不代表合规通过。报告包含原始证据、警告、未检查项和修正记录。HTML 报告可在浏览器打印为 PDF。</p>
      <div class="workflow-buttons">
        <button :disabled="!available || busy" @click="download('json')">导出 JSON</button>
        <button :disabled="!available || busy" @click="download('html')">导出 HTML</button>
      </div>
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
form { display: grid; gap: 12px; margin-top: 20px; }
label { display: grid; gap: 6px; }
input, select, textarea { font: inherit; width: 100%; box-sizing: border-box; padding: 10px; border: 1px solid #bbb; border-radius: 6px; background: var(--surface, white); color: inherit; }
button { font: inherit; padding: 10px 16px; border: 1px solid #888; border-radius: 6px; cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
.workflow-error { color: #b42318; }
</style>
