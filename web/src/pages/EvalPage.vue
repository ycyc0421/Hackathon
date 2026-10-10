<script setup>
/**
 * 评测看板。
 *
 * 核心约束：没有真实评测数据时必须显示"尚未评测"，
 * 不允许为了让页面好看而填入任何数字。
 * 契约里 Evaluation.status 的 NOT_RUN 就是为这一点设计的。
 */
import { ref, computed, inject, onMounted } from 'vue'
import { getEvaluation, USE_MOCK, ApiError } from '../api/index.js'
import { formatTime } from '../api/formatters.js'
import NoticeBar from '../components/NoticeBar.vue'
import SkeletonBlock from '../components/SkeletonBlock.vue'
import EmptyState from '../components/EmptyState.vue'

// 评测数据缓存由 App 层持有：切页重挂载时直接复用，不重复请求
const evaluation = inject('evaluation')
const evaluationLoaded = inject('evaluationLoaded')

const loading = ref(false)
const error = ref(null)

async function load() {
  if (loading.value) return
  loading.value = true
  error.value = null
  try {
    evaluation.value = await getEvaluation()
    evaluationLoaded.value = true
  } catch (e) {
    error.value =
      e instanceof ApiError ? e.message : '获取评测结果失败：前端与后端之间的请求未成功完成'
  } finally {
    loading.value = false
  }
}

// 只在首次进入（从未成功加载过）时自动请求；之后切回来复用缓存
onMounted(() => {
  if (!evaluationLoaded.value) load()
})

const isNotRun = computed(() => !evaluation.value || evaluation.value.status === 'NOT_RUN')
const isDone = computed(() => evaluation.value?.status === 'DONE')

/** 首次加载（还没有任何可显示内容）才显示骨架屏；之后的刷新保留旧内容 */
const loadingInitial = computed(() => loading.value && !evaluation.value && !error.value)

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

    <!-- 内容主体固定为一张卡片：各状态在同一骨架里淡入淡出，刷新不再引起布局坍塌。
         已有内容时刷新只降透明度，不卸载内容。 -->
    <section class="card eval-card" :class="{ refreshing: loading && !loadingInitial }">
      <Transition name="fade" mode="out-in">
        <!-- 首次读取：按"本次评测信息 + 指标表"的形状占位 -->
        <div v-if="loadingInitial" key="skeleton" class="eval-skeleton" aria-hidden="true">
          <SkeletonBlock width="140px" height="18px" />
          <div class="skeleton-meta-grid">
            <SkeletonBlock v-for="i in 4" :key="i" height="36px" />
          </div>
          <div class="eval-skeleton-table">
            <SkeletonBlock v-for="i in 3" :key="i" height="30px" />
          </div>
        </div>

        <!-- 加载失败：说清什么失败，提供重试 -->
        <EmptyState
          v-else-if="error"
          key="error"
          tone="bad"
          icon="⚠️"
          title="读取评测结果失败"
          :detail="error"
          :retrying="loading"
          retry-text="重试"
          @retry="load"
        />

        <!-- 尚未评测：这是默认状态，不是异常 -->
        <EmptyState
          v-else-if="isNotRun"
          key="not-run"
          tone="info"
          icon="📊"
          title="尚未评测"
          detail="尚无真实评测结果。本页在取得数据前不展示任何指标，以免与实际能力不符。"
        />

        <EmptyState
          v-else-if="evaluation?.status === 'RUNNING'"
          key="running"
          tone="info"
          icon="⏳"
          title="评测进行中"
          detail="跑分完成后可刷新查看。"
        />

        <EmptyState
          v-else-if="evaluation?.status === 'FAILED'"
          key="failed"
          tone="bad"
          icon="⚠️"
          title="评测失败"
          detail="本次跑分未产生结果。"
        />

        <div v-else-if="isDone" key="done" class="eval-done">
          <h3 class="card-title">本次评测信息</h3>
          <dl class="meta-grid">
            <div><dt>测试集版本</dt><dd>{{ evaluation.dataset_version ?? '—' }}</dd></div>
            <div><dt>样例数</dt><dd>{{ evaluation.sample_count }}</dd></div>
            <div><dt>模型版本</dt><dd>{{ evaluation.model_version ?? '—' }}</dd></div>
            <div><dt>运行时间</dt><dd>{{ formatTime(evaluation.run_at) }}</dd></div>
          </dl>

          <h3 class="card-title eval-section-title">指标</h3>
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

          <template v-if="errorBreakdown.length">
            <h3 class="card-title eval-section-title">错误分类</h3>
            <ul class="err-breakdown">
              <li v-for="e in errorBreakdown" :key="e.label">
                <span class="eb-label">{{ e.label }}</span>
                <span class="eb-count">{{ e.count }}</span>
              </li>
            </ul>
          </template>
        </div>
      </Transition>
    </section>

    <NoticeBar
      v-if="USE_MOCK"
      tone="info"
      title="当前使用示例数据"
      detail="后端评测接口尚未提供，本页显示的是占位状态。"
    />
  </div>
</template>
