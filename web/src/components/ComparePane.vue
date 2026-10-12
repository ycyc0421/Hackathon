<script setup>
/**
 * 并排对照面板：差异页比对卡片就地展开后的左右对照视图。
 *
 * 与 cmp-table 的关系：表格回答「每份文件各是什么值」，
 * 面板回答「几份文件摆在一起，差异在哪」——每份文件一列，
 * 值、原文、页码、字段状态并排列出。
 *
 * 降级原则：
 * - 「查看原文」按钮只在 App 层映射里真实拿到 File 对象时渲染
 *   （mock 场景无 File，按钮不渲染，只看并排值对照）；
 * - page 为 null 时不显示页码，也不拼 #page 锚；
 * - normalized_value 为 null 显示「—」，不用任何默认值冒充。
 */
import { computed, inject, onBeforeUnmount } from 'vue'
import { formatValue, fieldStatus } from '../api/formatters.js'
import { divergenceInfo } from '../utils/divergence.js'
import { evidenceRawText } from '../utils/evidence.js'
import { isEdiName } from '../api/uploadLimits.js'
import StatusBadge from './StatusBadge.vue'
import EdiSourceView from './EdiSourceView.vue'

const props = defineProps({
  comparison: { type: Object, required: true },
  /** 抽取层原文证据索引（DiffPage 由 task.extractions 构建）；缺省时不做证据回退 */
  evidenceIndex: { type: Object, default: null },
})

const sourceFiles = inject('sourceFiles')

/** 本次会话内创建的 objectURL，组件卸载时统一回收 */
const objectUrls = new Set()

function valueText(v) {
  const { main, sub } = formatValue(v.normalized_value, props.comparison.value_type, props.comparison.unit)
  return sub ? `${main} ${sub}` : main
}

function hasValue(v) {
  return v.normalized_value !== null && v.normalized_value !== undefined
}

/** 归一值与原文写法不同时才显示原文，避免同值重复两遍 */
function showsRaw(v) {
  if (!v.raw_value) return false
  const { main } = formatValue(v.normalized_value, props.comparison.value_type, props.comparison.unit)
  return String(v.raw_value).trim() !== String(main).trim()
}

/**
 * raw_value 读不出值时的证据回退：抽取层保留的原文片段 raw_text。
 * 关联键 file_id + item_id + field_key，多商品不串证据；没有证据时返回 null。
 */
function rawEvidence(v) {
  return evidenceRawText(props.evidenceIndex, props.comparison, v)
}

function fileStatusOf(v) {
  return fieldStatus(v.field_status)
}

function sourceFileOf(v) {
  return sourceFiles.get(v.file_name)
}

/** CONFLICT 时按多数派规则标出不同列；无基准（全不同/并列）时全标 */
const divergence = computed(() => divergenceInfo(props.comparison))

function isDivergent(v) {
  return divergence.value.divergent.has(v.file_id)
}

function isPdf(file) {
  return file.name.split('.').pop()?.toUpperCase() === 'PDF'
}

/**
 * 新窗口打开原文。PDF 且知道页码时拼 #page= 锚，浏览器自带 viewer 会跳到该页；
 * 图片等非 PDF 直接开 objectURL（#page 对它们无意义）。
 * objectURL 延迟回收：新窗口加载需要时间，立刻 revoke 会打开空白页。
 */
function openSource(v) {
  const file = sourceFileOf(v)
  if (!file) return
  let url = URL.createObjectURL(file)
  objectUrls.add(url)
  if (isPdf(file) && v.page != null) url += `#page=${v.page}`
  window.open(url, '_blank', 'noopener')
  setTimeout(() => {
    URL.revokeObjectURL(url.split('#')[0])
    objectUrls.delete(url.split('#')[0])
  }, 60_000)
}

onBeforeUnmount(() => {
  for (const url of objectUrls) URL.revokeObjectURL(url)
  objectUrls.clear()
})
</script>

<template>
  <div class="compare-pane">
    <p v-if="comparison.status === 'CONFLICT' && !divergence.hasMajority" class="compare-basis-note">
      各文件取值互不相同，没有可作基准的多数值
    </p>
    <div class="compare-cols">
      <div
        v-for="v in comparison.values"
        :key="v.file_id"
        class="compare-col"
        :class="{ divergent: isDivergent(v) }"
      >
        <div class="compare-file" :title="v.file_name">{{ v.file_name }}</div>

        <div class="compare-value-row">
          <span v-if="hasValue(v)" class="compare-value">{{ valueText(v) }}</span>
          <span v-else class="compare-value empty">—</span>
          <span v-if="v.page != null" class="compare-page">第 {{ v.page }} 页</span>
        </div>

        <div v-if="showsRaw(v)" class="compare-raw">原文：{{ v.raw_value }}</div>
        <!-- raw_value 为空时回退展示抽取层原文片段，标注为片段、不冒充归一值 -->
        <div v-else-if="rawEvidence(v)" class="compare-raw">原文片段：{{ rawEvidence(v) }}</div>

        <div class="compare-foot">
          <StatusBadge :status="fileStatusOf(v)" />
          <!-- EDI 走共享查看组件：纯文本 + 下载，不拼 #page、不新开窗口（#40）；
               PDF/图片保持原有的新窗口 objectURL 路径 -->
          <EdiSourceView
            v-if="sourceFileOf(v) && isEdiName(v.file_name)"
            :file="sourceFileOf(v)"
            class="compare-foot-source"
          />
          <button
            v-else-if="sourceFileOf(v)"
            class="link-btn"
            @click="openSource(v)"
          >
            查看原文{{ v.page != null && isPdf(sourceFileOf(v)) ? `第 ${v.page} 页` : '' }} ↗
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
