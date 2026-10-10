<script setup>
/**
 * 评测看板。
 *
 * 核心约束：没有真实评测数据时必须显示"尚未评测"，
 * 不允许为了让页面好看而填入任何数字。
 * 契约里 Evaluation.status 的 NOT_RUN 就是为这一点设计的。
 */
import { ref, computed, onMounted } from 'vue'
import { getEvaluation, USE_MOCK, ApiError } from '../api/index.js'
import { formatTime } from '../api/formatters.js'
import NoticeBar from '../components/NoticeBar.vue'
import SkeletonBlock from '../components/SkeletonBlock.vue'
import EmptyState from '../components/EmptyState.vue'

const evaluation = ref(null)
const loading = ref(false)
const error = ref(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    evaluation.value = await getEvaluation()
  } catch (e) {
    error.value =
      e instanceof ApiError ? e.message : '获取评测结果失败：前端与后端之间的请求未成功完成'
  } finally {
    loading.value = false
  }
}

onMounted(load)

const isNotRun = computed(() => !evaluation.value || evaluation.value.status === 'NOT_RUN')
const isDone = computed(() => evaluation.value?.status === 'DONE')

/** 指标分组的中文名。统计口径需数据侧与后端侧确认 */
const METRIC_GROUPS = [
  { key: 'field_extraction', label: '字段抽取' },
  { key: 'conflict_detection', label: '冲突检出' },
  { key: 'risk_hint', label: '风险提示' },
]

const metricRows = computed(() => {
  const m = evaluation.value?.metrics
  if (!m) return []
  return METRIC_GROUPS.filter((g) => m[g.key]).map((g) => ({
    label: g.label,
    ...m[g.key],
  }))
})

function pct(v) {
  if (v === null || v === undefined) return '—'
  return `${(v * 100).toFixed(1)}%`
}

const errorBreakdown = computed(() => {
  const b = evaluation.value?.error_breakdown
  if (!b) return []
  return Object.entries(b).map(([k, v]) => ({ label: k, count: v }))
})
</script>

<template>
  <div class="page">
    <div class="section-head">
      <h2 class="section-title">评测结果</h2>
      <button class="btn small" :disabled="loading" @click="load">
        {{ loading ? '读取中…' : '刷新' }}
      </button>
    </div>

    <!-- 加载失败：说清什么失败，提供重试 -->
    <EmptyState
      v-if="error"
      tone="bad"
      icon="⚠️"
      title="读取评测结果失败"
      :detail="error"
      :retrying="loading"
      retry-text="重试"
      @retry="load"
    />

    <!-- 首次读取中：按"本次评测信息 + 指标表"的形状占位 -->
    <template v-if="loading && !evaluation">
      <section class="card" aria-hidden="true">
        <SkeletonBlock width="140px" height="18px" />
        <div class="skeleton-meta-grid">
          <SkeletonBlock v-for="i in 4" :key="i" height="36px" />
        </div>
      </section>
      <section class="card" aria-hidden="true">
        <SkeletonBlock width="80px" height="18px" />
        <SkeletonBlock v-for="i in 3" :key="i" height="30px" />
      </section>
    </template>

    <!-- 尚未评测：这是默认状态，不是异常 -->
    <EmptyState
      v-else-if="isNotRun && !loading"
      tone="info"
      icon="📊"
      title="尚未评测"
      detail="尚无真实评测结果。本页在取得数据前不展示任何指标，以免与实际能力不符。"
    />

    <NoticeBar
      v-else-if="evaluation?.status === 'RUNNING'"
      tone="info"
      title="评测进行中"
      detail="跑分完成后可刷新查看。"
    />

    <NoticeBar
      v-else-if="evaluation?.status === 'FAILED'"
      tone="bad"
      title="评测失败"
      detail="本次跑分未产生结果。"
    />

    <template v-if="isDone">
      <section class="card">
        <h2 class="card-title">本次评测信息</h2>
        <dl class="meta-grid">
          <div><dt>测试集版本</dt><dd>{{ evaluation.dataset_version ?? '—' }}</dd></div>
          <div><dt>样例数</dt><dd>{{ evaluation.sample_count }}</dd></div>
          <div><dt>模型版本</dt><dd>{{ evaluation.model_version ?? '—' }}</dd></div>
          <div><dt>运行时间</dt><dd>{{ formatTime(evaluation.run_at) }}</dd></div>
        </dl>
      </section>

      <section class="card">
        <h2 class="card-title">指标</h2>
        <table class="metric-table">
          <thead>
            <tr>
              <th>项目</th>
              <th>精确率</th>
              <th>召回率</th>
              <th>F1</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in metricRows" :key="row.label">
              <td>{{ row.label }}</td>
              <td class="num">{{ pct(row.precision) }}</td>
              <td class="num">{{ pct(row.recall) }}</td>
              <td class="num">{{ pct(row.f1) }}</td>
            </tr>
          </tbody>
        </table>
        <p class="foot-note">
          指标口径（采用哪几项、如何计算）需与提供评测结果的一方确认，本页不设达标阈值。
        </p>
      </section>

      <section v-if="errorBreakdown.length" class="card">
        <h2 class="card-title">错误分类</h2>
        <ul class="err-breakdown">
          <li v-for="e in errorBreakdown" :key="e.label">
            <span class="eb-label">{{ e.label }}</span>
            <span class="eb-count">{{ e.count }}</span>
          </li>
        </ul>
      </section>
    </template>

    <NoticeBar
      v-if="USE_MOCK"
      tone="info"
      title="当前使用示例数据"
      detail="后端评测接口尚未提供，本页显示的是占位状态。"
    />
  </div>
</template>
