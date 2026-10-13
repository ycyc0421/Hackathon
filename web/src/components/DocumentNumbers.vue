<script setup>
/**
 * 文件自身的单据编号（document_no）展示。
 *
 * 用途：报告页文件清单里，在每份文件名下补一行它自己的编号。
 * 数据只按 file_id 关联——同一份上传里可能有同名文件，documents 与
 * extractions 的顺序也不保证一致，按数组位置或文件名取值都会串号。
 *
 * 契约边界：
 * - document_no 是「各文件自身编号」，属于兼容新增的抽取字段，不参加跨单据
 *   相等比较（invoice_no 的商业发票引用语义不变，这里不回退到它）；
 * - 老任务没有 document_no 时整行隐藏，不合成编号、不标缺失异常；
 * - 整票字段的 item_id 与 line_no 均为空；item_id 为空但带 line_no 的是
 *   未分组商品行，不冒充文件级编号；
 * - confidence 为 null 不显示百分比；原文片段用文本插值保留换行，不 v-html。
 */
import { computed } from 'vue'
import { fieldStatus, formatValue, confidenceText } from '../api/formatters.js'
import StatusBadge from './StatusBadge.vue'

const props = defineProps({
  /** 当前文件清单项对应的 document（取其 file_id） */
  document: { type: Object, required: true },
  /** 整个 task.extractions；组件内部按 file_id 找对应抽取结果 */
  extractions: { type: Array, default: () => [] },
})

/**
 * 该文件的 document_no 整票字段。
 * 只取 field_key==='document_no' 且 item_id/line_no 均为空的文件级字段；
 * 查不到返回 null，调用方隐藏整行，不制造缺失提示。
 */
const field = computed(() => {
  const fileId = props.document?.file_id
  if (!fileId) return null
  const ext = (props.extractions ?? []).find((e) => e?.file_id === fileId)
  if (!ext) return null
  return (
    (ext.fields ?? []).find(
      (f) =>
        f?.field_key === 'document_no' &&
        (f.item_id ?? null) === null &&
        (f.line_no ?? null) === null
    ) ?? null
  )
})

/** 字段状态徽章；EXTRACTED 文案为空，StatusBadge 自动不渲染 */
const status = computed(() => (field.value ? fieldStatus(field.value.status) : null))

/** 有效值（normalized_value）；按 value_type/unit 走统一格式化，CODE 类原样显示 */
const effective = computed(() => {
  if (!field.value) return null
  const { main, sub } = formatValue(field.value.normalized_value, field.value.value_type, field.value.unit)
  return field.value.normalized_value === null || field.value.normalized_value === undefined
    ? null
    : sub
      ? `${main} ${sub}`
      : main
})

/** 原始读数（raw_value）：与有效值分开标记，不混为一谈 */
const rawValue = computed(() => {
  const v = field.value?.raw_value
  return v === null || v === undefined || v === '' ? null : String(v)
})

/** 原文片段（raw_text）：可能多行，用 white-space: pre-wrap 保留换行 */
const rawText = computed(() => {
  const t = field.value?.raw_text
  return typeof t === 'string' && t.trim() ? t : null
})

/** 是否有可展开的原始信息（原始读数或原文片段） */
const hasDetail = computed(() => Boolean(rawValue.value || rawText.value))

/** confidence 为 null 时不显示；有值才给百分比 */
const confidence = computed(() => confidenceText(field.value?.confidence))

/** 后端 label 缺失时不建中文映射，给通用提示并记为无效响应场景 */
const label = computed(() => field.value?.label || '未提供字段名称')
</script>

<template>
  <!-- 没有 document_no（老任务/未抽取到）时整体不渲染，回退为零占位 -->
  <div v-if="field" class="docno">
    <div class="docno-head">
      <span class="docno-label">{{ label }}</span>
      <StatusBadge :status="status" />
    </div>
    <div class="docno-body">
      <span v-if="effective" class="docno-value">{{ effective }}</span>
      <span v-else class="docno-value empty">—</span>
      <span v-if="confidence" class="docno-confidence">{{ confidence }}</span>
    </div>
    <!-- 原始读数与原文片段默认收起，展开控件可键盘操作（原生 details/summary） -->
    <details v-if="hasDetail" class="docno-detail">
      <summary class="docno-toggle">原始读数与原文</summary>
      <div class="docno-detail-body">
        <div v-if="rawValue" class="docno-row">
          <span class="docno-row-key">原始读数</span>
          <span class="docno-row-val">{{ rawValue }}</span>
        </div>
        <div v-if="rawText" class="docno-row">
          <span class="docno-row-key">原文片段</span>
          <span class="docno-row-val docno-raw">{{ rawText }}</span>
        </div>
      </div>
    </details>
  </div>
</template>

<style scoped>
/* 局部样式挂在文件清单的 doc-chip 内，独立于全局 styles.css，避免并行改动冲突 */
.docno {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--border, #ddd);
  font-size: var(--text-xs, 12px);
  line-height: 1.5;
  min-width: 0;
}

.docno-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.docno-label {
  color: var(--text-muted, #666);
}

.docno-body {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 2px;
}

.docno-value {
  font-weight: 600;
  word-break: break-all;
}

.docno-value.empty {
  color: var(--text-muted, #666);
  font-weight: 400;
}

.docno-confidence {
  color: var(--text-muted, #666);
}

.docno-toggle {
  cursor: pointer;
  color: var(--info, #2563eb);
  margin-top: 4px;
  user-select: none;
}

.docno-detail-body {
  margin-top: 4px;
  display: grid;
  gap: 4px;
}

.docno-row {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 8px;
  align-items: start;
}

.docno-row-key {
  color: var(--text-muted, #666);
  white-space: nowrap;
}

.docno-row-val {
  word-break: break-all;
  min-width: 0;
}

/* 原文片段保留换行；长编号/多行原文在窄屏可换行阅读 */
.docno-raw {
  white-space: pre-wrap;
}
</style>
