<script setup>
/**
 * 评测看板。
 *
 * 核心约束：没有真实评测数据时必须显示"尚未评测"，
 * 不允许为了让页面好看而填入任何数字。
 * 契约里 Evaluation.status 的 NOT_RUN 就是为这一点设计的。
 */
import { ref, computed, inject, onMounted } from 'vue'
import { getEvaluation, getEvaluationRuns, isMock, ApiError } from '../api/index.js'
import { backendErrorText } from '../api/errors.js'
import { formatTime } from '../api/formatters.js'
import { EVALUATION_SPLITS } from '../api/labels.js'
import NoticeBar from '../components/NoticeBar.vue'
import SkeletonBlock from '../components/SkeletonBlock.vue'
import EmptyState from '../components/EmptyState.vue'
import AppSelect from '../components/AppSelect.vue'

// 评测数据缓存由 App 层持有：切页重挂载时直接复用，不重复请求
const evaluation = inject('evaluation')
const evaluationLoaded = inject('evaluationLoaded')

/** 示例数据横幅只在 mock 数据源下出现（App 顶栏的「示例数据」徽标同款） */
const mock = ref(isMock())

const loading = ref(false)
const error = ref(null)
const runs = ref([])
const selectedRun = ref('')
const scope = computed(() => evaluation.value?.scope)
const runOptions = computed(() => runs.value.map((run, index) => ({
  value: String(index),
  label: [run.scope?.input_kind ?? '范围未记录', run.sample_count + ' 票', formatTime(run.run_at)].join(' · '),
})))

function chooseRun(index) {
  evaluation.value = runs.value[Number(index)]
}

async function load() {
  if (loading.value) return
  loading.value = true
  error.value = null
  try {
    const [latest, history] = await Promise.all([getEvaluation(), getEvaluationRuns()])
    evaluation.value = latest
    runs.value = history
    selectedRun.value = String(history.findIndex((run) => run.run_at === latest.run_at))
    evaluationLoaded.value = true
  } catch (e) {
    error.value =
      e instanceof ApiError
        ? e.kind === 'SERVER'
          ? backendErrorText(e)
          : e.message
        : '获取评测结果失败：前端与后端之间的请求未成功完成'
  } finally {
    loading.value = false
  }
}

// 保留旧摘要作为读取占位，每次进入重新读取批次，接收后端新发布的结果。
onMounted(load)

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
    key: g.key,
    label: g.label,
    ...m[g.key],
    counts: scope.value?.counts?.[g.key],
    definition: scope.value?.metric_definitions?.[g.key],
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

/** 错误分类条形图的归一基准：取最大计数。全为 0 时退回 1，避免除零产生 NaN 宽度 */
const maxErrCount = computed(() =>
  Math.max(1, ...errorBreakdown.value.map((e) => e.count ?? 0)),
)
</script>

<template>
  <div class="page">
    <div class="section-head">
      <h2 class="section-title">系统评测</h2>
      <button class="btn small" :disabled="loading" @click="load">
        {{ loading ? '读取中…' : '刷新' }}
      </button>
    </div>
    <p class="page-desc">查看固定数据集上的实测表现。普通上传不会启动评测；刷新只读取已保存的结果。</p>
    <div v-if="runs.length" class="field">
      <span id="evaluation-run-label" class="field-label">选择评测批次</span>
      <AppSelect v-model="selectedRun" :options="runOptions" :disabled="loading" block
        aria-labelledby="evaluation-run-label" @change="chooseRun" />
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
          title="尚未评测"
          detail="尚无已保存的评测结果。需要先对固定样本与金标运行评测，再由后端发布摘要；上传普通单证不会产生这里的分数。"
        />

        <EmptyState
          v-else-if="evaluation?.status === 'RUNNING'"
          key="running"
          tone="info"
          title="评测进行中"
          detail="跑分完成后可刷新查看。"
        />

        <EmptyState
          v-else-if="evaluation?.status === 'FAILED'"
          key="failed"
          tone="bad"
          title="评测失败"
          detail="本次结果无法读取或校验失败，暂不展示指标。请检查后端评测文件。"
        />

        <div v-else-if="isDone" key="done" class="eval-done">
          <NoticeBar tone="info" :title="scope?.input_kind ?? '本批次未记录评测范围'"
            :detail="scope ? scope.dataset_kind + '；完成跑分不代表达到质量要求。' : '请先核对数据来源和计分口径，不据此推断完整模型能力。'" />
          <h3 class="card-title">本次评测信息</h3>
          <dl class="meta-grid">
            <div><dt>测试集版本</dt><dd>{{ evaluation.dataset_version ?? '—' }}</dd></div>
            <div><dt>货票数</dt><dd>{{ evaluation.sample_count }}</dd></div>
            <div v-if="scope"><dt>文件数</dt><dd>{{ scope.document_count }}</dd></div>
            <div><dt>被测流水线 / 模型</dt><dd>{{ evaluation.model_version ?? '—' }}</dd></div>
            <div><dt>运行时间</dt><dd>{{ formatTime(evaluation.run_at) }}</dd></div>
            <div v-if="scope"><dt>数据划分</dt><dd>{{ EVALUATION_SPLITS[scope.split] ?? scope.split }}</dd></div>
          </dl>

          <h3 class="card-title eval-section-title">指标</h3>
          <!-- 每个指标一组：三项各自一条比例条 + 数值。
               条形只表示 0–100% 的比例，不画"达标线"——本页不设阈值。 -->
          <div class="metric-cards">
            <article v-for="row in metricRows" :key="row.key" class="metric-card">
              <h4 class="metric-card-title">{{ row.label }}</h4>
              <div
                v-for="m in [
                  { key: 'precision', label: '精确率', value: row.precision, tone: 'p' },
                  { key: 'recall', label: '召回率', value: row.recall, tone: 'r' },
                  { key: 'f1', label: 'F1', value: row.f1, tone: 'f' },
                ]"
                :key="m.key"
                class="metric-row"
                :class="`metric-row--${m.tone}`"
              >
                <span class="metric-label">{{ m.label }}</span>
                <span class="metric-track" aria-hidden="true">
                  <span
                    class="metric-fill"
                    :style="`width:${m.value == null ? 0 : Math.max(0, Math.min(1, m.value)) * 100}%`"
                  />
                </span>
                <span class="metric-value">{{ pct(m.value) }}</span>
              </div>
              <p v-if="row.counts" class="foot-note">
                正确 {{ row.counts.tp }} · 多报 {{ row.counts.fp }} · 漏报 {{ row.counts.fn }}<br />
                预测项 {{ row.counts.tp + row.counts.fp }} · 金标项 {{ row.counts.tp + row.counts.fn }}
              </p>
              <p v-if="row.definition" class="foot-note">{{ row.definition }}</p>
            </article>
          </div>
          <p class="foot-note">
            分母为零显示“—”；本页不设达标阈值。字段错值会同时计为多报与漏报，错误分类不可直接相加。
          </p>
          <p v-if="!evaluation.metrics?.risk_hint" class="foot-note">风险提示：本批次未评测，不代表没有风险。</p>
          <section v-if="scope" class="eval-section-title">
            <h3 class="card-title">范围与局限</h3>
            <ul><li v-for="limitation in scope.limitations" :key="limitation">{{ limitation }}</li></ul>
            <details class="eval-provenance">
              <summary>版本与数据指纹</summary>
              <p>被测提交：{{ scope.code_revision }}</p>
              <p>计分版本：{{ scope.scorer_version }}</p>
              <p>数据指纹：{{ scope.dataset_sha256 }}</p>
            </details>
          </section>

          <template v-if="errorBreakdown.length">
            <h3 class="card-title eval-section-title">错误分类</h3>
            <!-- 横向条形：按最大计数归一，让各条之间的相对量级可读 -->
            <ul class="err-breakdown">
              <li v-for="e in errorBreakdown" :key="e.label">
                <span class="eb-label">{{ e.label }}</span>
                <span class="eb-track" aria-hidden="true">
                  <span class="eb-fill" :style="`width:${(e.count / maxErrCount) * 100}%`" />
                </span>
                <span class="eb-count">{{ e.count }}</span>
              </li>
            </ul>
          </template>
        </div>
      </Transition>
    </section>

    <NoticeBar
      v-if="mock"
      tone="info"
      title="当前使用示例数据"
      detail="本页显示的是内置示例评测结果，并非真实跑分，数值不代表实际能力。"
    />
  </div>
</template>

<style scoped>
.meta-grid dd, .eval-provenance { overflow-wrap: anywhere; }
.eval-provenance, .eval-section-title ul { font-size: var(--text-sm); color: var(--text-muted); }
.eval-done > .notice { margin-bottom: var(--space-5); }
</style>
