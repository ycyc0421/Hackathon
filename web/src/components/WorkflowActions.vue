<script setup>
import { computed, inject, ref, watch } from 'vue'
import { API_BASE, isMock } from '../api/config.js'
import { requestOnce } from '../api/request.js'

const task = inject('task')
const taskError = inject('taskError', null)
const documentKeys = new Set(['packages','gross_weight','net_weight','volume','quantity','hs_code','total_amount','currency','description','invoice_no','shipment_date','bill_of_lading_no','contract_no','container_no','shipper','consignee','port_of_loading','port_of_discharge'])
const itemKeys = new Set(['item_code','description','hs_code','quantity','packages','net_weight','gross_weight','volume','unit_price','amount'])
const busy = ref(false)
const error = ref('')
const message = ref('')
const selection = ref('')
const value = ref('')
const reason = ref('')
let pending = null
const terminal = computed(() => ['COMPLETED','PARTIAL','FAILED'].includes(task.value?.status))
const available = computed(() => !isMock() && terminal.value && !taskError?.value)
const editable = computed(() => available.value && ['COMPLETED','PARTIAL'].includes(task.value?.status))
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
watch([selection,value,reason], () => { pending = null })
watch(() => task.value?.task_id, () => { selection.value = ''; value.value = ''; reason.value = ''; pending = null; error.value = '' })

async function revise() {
  if (!editable.value || !chosen.value || !value.value.trim() || !reason.value.trim() || busy.value) return
  busy.value = true; error.value = ''; message.value = ''
  const sourceId = task.value.task_id
  try {
    if (!pending) {
      const source = await requestOnce(`/checks/${encodeURIComponent(sourceId)}/corrections`, {}, { base: API_BASE })
      pending = {
        request_id: crypto.randomUUID(), source_hash: source.result_hash, reason: reason.value,
        changes: [{ file_id: chosen.value.file_id, item_no: chosen.value.item_no, field_key: chosen.value.field_key, value: value.value }],
      }
    }
    const child = await requestOnce(`/checks/${encodeURIComponent(sourceId)}/corrections`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(pending),
    }, { base: API_BASE })
    if (task.value?.task_id === sourceId) {
      task.value = child
      message.value = '已创建修正任务并重算。原任务和原始证据保留，报告包含修正审计。'
    }
  } catch (e) { error.value = e.message || '修正失败，请重试' }
  finally { busy.value = false }
}

async function download(format) {
  if (!available.value || busy.value) return
  busy.value = true; error.value = ''
  const id = task.value.task_id
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), 30000)
  try {
    const response = await fetch(`${API_BASE}/checks/${encodeURIComponent(id)}/report?format=${format}`, { signal: ctrl.signal })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(body?.error?.message || `导出失败（HTTP ${response.status}）`)
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url; anchor.download = `report-${id}.${format}`; anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) { error.value = e.name === 'AbortError' ? '导出超时，请重试' : (e.message || '导出失败') }
  finally { clearTimeout(timer); busy.value = false }
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
