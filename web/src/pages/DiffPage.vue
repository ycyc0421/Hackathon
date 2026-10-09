<script setup>
/**
 * 差异页：展示抽取字段与跨文件比对结果。
 *
 * 设计要点：
 * - 逐条比对都要能回答「哪份文件、什么值、是否一致」，不允许只给一个笼统的红色提示。
 * - MATCH 之外的每种状态都要显示，尤其 NOT_CHECKED（未校验）——
 *   它必须与「没有问题」在视觉上区分开。
 */
import { ref, computed, inject } from 'vue'
import {
  comparisonStatus,
  fieldStatus,
  severity,
  formatValue,
  confidenceText,
} from '../api/formatters.js'
import StatusBadge from '../components/StatusBadge.vue'
import NoticeBar from '../components/NoticeBar.vue'

const task = inject('task')

const filter = ref('problems') // all | problems | conflicts | unchecked

const comparisons = computed(() => task.value?.comparisons ?? [])

const counts = computed(() => {
  const list = comparisons.value
  return {
    total: list.length,
    conflict: list.filter((c) => c.status === 'CONFLICT').length,
    missing: list.filter((c) => c.status === 'MISSING_IN_SOME').length,
    unchecked: list.filter((c) => c.status === 'NOT_CHECKED').length,
    unrecognized: list.filter((c) => c.status === 'UNRECOGNIZED').length,
    match: list.filter((c) => c.status === 'MATCH').length,
    single: list.filter((c) => c.status === 'SINGLE_SOURCE').length,
  }
})

/** 「有问题」= 需要人看一眼的，包括未校验 */
const problemStatuses = ['CONFLICT', 'MISSING_IN_SOME', 'NOT_CHECKED', 'UNRECOGNIZED']

const visible = computed(() => {
  const list = comparisons.value
  switch (filter.value) {
    case 'problems':
      return list.filter((c) => problemStatuses.includes(c.status))
    case 'conflicts':
      return list.filter((c) => c.status === 'CONFLICT')
    case 'unchecked':
      return list.filter((c) => c.status === 'NOT_CHECKED')
    default:
      return list
  }
})

function fileStatusOf(v) {
  return fieldStatus(v.field_status)
}

function valueText(v, comparison) {
  const { main, sub } = formatValue(v.normalized_value, comparison.value_type, comparison.unit)
  return sub ? `${main} ${sub}` : main
}

/** 归一值与原文写法不同时，把原文也显示出来，便于人工核对 */
function showsRaw(v, comparison) {
  if (!v.raw_value) return false
  const { main } = formatValue(v.normalized_value, comparison.value_type, comparison.unit)
  return String(v.raw_value).trim() !== String(main).trim()
}

const severityOf = severity
</script>

<template>
  <div class="page">
    <NoticeBar
      v-if="!task"
      tone="info"
      title="尚无检查结果"
      detail="请先在「上传」页创建一次检查。"
    />

    <template v-else>
      <!-- PARTIAL 必须在差异页也提醒一次，用户可能直接跳到这里 -->
      <NoticeBar
        v-if="task.status === 'PARTIAL'"
        tone="warn"
        title="本次结果不完整"
        detail="有文件未能处理成功，相关比对缺少这些文件的数据。"
      />
      <NoticeBar
        v-else-if="task.status === 'FAILED'"
        tone="bad"
        title="检查失败"
        detail="未产生比对结果。"
      />

      <section v-if="comparisons.length" class="card">
        <div class="filter-row">
          <button class="chip" :class="{ active: filter === 'problems' }" @click="filter = 'problems'">
            需关注 <span class="chip-num">{{ counts.conflict + counts.missing + counts.unchecked + counts.unrecognized }}</span>
          </button>
          <button class="chip" :class="{ active: filter === 'conflicts' }" @click="filter = 'conflicts'">
            不一致 <span class="chip-num">{{ counts.conflict }}</span>
          </button>
          <button class="chip" :class="{ active: filter === 'unchecked' }" @click="filter = 'unchecked'">
            未校验 <span class="chip-num">{{ counts.unchecked }}</span>
          </button>
          <button class="chip" :class="{ active: filter === 'all' }" @click="filter = 'all'">
            全部 <span class="chip-num">{{ counts.total }}</span>
          </button>
        </div>

        <p class="filter-note">
          「未校验」指当前规则集未覆盖该字段，并非表示没有问题。
        </p>

        <ul v-if="visible.length" class="cmp-list">
          <li v-for="c in visible" :key="c.comparison_id" class="cmp-item">
            <div class="cmp-head">
              <div class="cmp-title">
                <span class="cmp-label">{{ c.label }}</span>
                <span class="cmp-key">{{ c.field_key }}</span>
              </div>
              <div class="cmp-badges">
                <StatusBadge :status="severityOf(c.severity)" />
                <StatusBadge :status="comparisonStatus(c.status)" />
              </div>
            </div>

            <p v-if="c.note" class="cmp-note">{{ c.note }}</p>

            <table class="cmp-table">
              <thead>
                <tr>
                  <th>来源文件</th>
                  <th>值</th>
                  <th>原文</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="v in c.values" :key="v.file_id" :class="{ 'row-odd': v.field_status !== 'EXTRACTED' }">
                  <td class="cell-file">{{ v.file_name }}</td>
                  <td class="cell-value">
                    <template v-if="v.normalized_value !== null && v.normalized_value !== undefined">
                      {{ valueText(v, c) }}
                    </template>
                    <span v-else class="cell-empty">—</span>
                  </td>
                  <td class="cell-raw">
                    <template v-if="showsRaw(v, c)">{{ v.raw_value }}</template>
                    <span v-else class="cell-empty">—</span>
                  </td>
                  <td><StatusBadge :status="fileStatusOf(v)" /></td>
                </tr>
              </tbody>
            </table>

            <div v-if="c.rule_id" class="cmp-foot">依据规则 {{ c.rule_id }}</div>
            <div v-else class="cmp-foot muted">未经规则校验</div>
          </li>
        </ul>

        <p v-else class="empty">
          当前筛选下没有条目。切到「全部」可查看一致字段。
        </p>
      </section>

      <section v-else class="card">
        <p class="empty">后端未返回任何比对结果。</p>
      </section>
    </template>
  </div>
</template>
