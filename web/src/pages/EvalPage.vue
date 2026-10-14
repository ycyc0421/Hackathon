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
import { EVALUATION_SPLITS, EVALUATION_METRICS, EVALUATION_TEXT } from '../api/labels.js'
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

const metricRows = computed(() => {
  const m = evaluation.value?.metrics
  if (!m) return []
  /* 按 EVALUATION_METRICS 的顺序出卡片，不遍历 metrics 的键：
     $defs.Metrics 是 additionalProperties:false，后端不可能合法地多出第四项。
     scope.metric_definitions 则相反（additionalProperties: string），
     那里要按实际键展示，不能只认这三项。 */
  return Object.entries(EVALUATION_METRICS)
    .filter(([key]) => m[key])
    .map(([key, label]) => ({
      key,
      label,
      ...m[key],
      counts: scope.value?.counts?.[key] ?? null,
      definition: scope.value?.metric_definitions?.[key],
    }))
})

/** 指标口径：契约给的是「指标名 → 一段中文说明」，键可能超出页面已知的指标 */
const definitionRows = computed(() => {
  const defs = scope.value?.metric_definitions
  if (!defs) return []
  return Object.entries(defs).map(([key, text]) => ({
    key,
    label: EVALUATION_METRICS[key] ?? key,
    text,
  }))
})

const limitations = computed(() => scope.value?.limitations ?? [])

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
    <p class="page-sub">查看固定数据集上的实测表现。普通上传不会启动评测；刷新只读取已保存的结果。</p>
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
          <!-- 范围提示条：说清这份分数是在什么通道、什么数据上得到的。
               scope 是契约里的可选字段，旧结果没有——那时如实说明范围未记录，
               不能省略这一段（省略会被读成"没有范围限制"）。 -->
          <NoticeBar
            tone="info"
            :title="scope?.input_kind ?? '本批次未记录评测范围'"
            :detail="scope ? scope.dataset_kind + '；完成跑分不代表达到质量要求。' : EVALUATION_TEXT.scopeMissing"
          />

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
              <!-- 计数与比例同源、同卡并置：比例就是计数的换算，并排才能当场验算。
                   该指标没有计数时整条不渲染（不补 0、不显示 0/0）。 -->
              <dl v-if="row.counts" class="metric-counts">
                <div>
                  <dt>命中<span class="metric-count-abbr">TP</span></dt>
                  <dd>{{ row.counts.tp }}</dd>
                </div>
                <div>
                  <dt>误报<span class="metric-count-abbr">FP</span></dt>
                  <dd>{{ row.counts.fp }}</dd>
                </div>
                <div>
                  <dt>漏检<span class="metric-count-abbr">FN</span></dt>
                  <dd>{{ row.counts.fn }}</dd>
                </div>
              </dl>
            </article>
          </div>
          <p class="foot-note">{{ EVALUATION_TEXT.formula }}本页不设达标阈值。</p>
          <!-- 契约允许某指标只给计数不给分数（当前跑分不计风险提示），
               缺了要明说，不能让读者把"没评"读成"没问题" -->
          <p v-if="!evaluation.metrics?.risk_hint" class="foot-note">风险提示：本批次未评测，不代表没有风险。</p>

          <template v-if="limitations.length">
            <h3 class="card-title eval-section-title">已知局限</h3>
            <!-- limitations 在契约里就是成句中文，不是语义代码：逐条直出，
                 不建立代码→文案映射（那套映射会静默丢掉后端新增的条目） -->
            <ul class="limit-list">
              <li v-for="(limitation, i) in limitations" :key="i">{{ limitation }}</li>
            </ul>
          </template>

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
            <p class="foot-note">{{ EVALUATION_TEXT.breakdownNote }}</p>
          </template>

          <!-- 指标口径与复现证据：口径可能很长，64 位指纹也不适合摆在正文里，
               两者都是"这份分数怎么来的"，收在同一个可展开块里，正文只留结论。 -->
          <details v-if="scope" class="eval-provenance">
            <summary>指标口径与复现证据</summary>
            <template v-if="definitionRows.length">
              <h4 class="eval-provenance-title">指标口径</h4>
              <dl class="definition-list">
                <div v-for="d in definitionRows" :key="d.key">
                  <dt>{{ d.label }}</dt>
                  <dd>{{ d.text }}</dd>
                </div>
              </dl>
            </template>
            <h4 class="eval-provenance-title">复现指纹</h4>
            <p>被测提交：{{ scope.code_revision }}</p>
            <p>计分版本：{{ scope.scorer_version }}</p>
            <p>数据集指纹（SHA-256）：{{ scope.dataset_sha256 }}</p>
            <p class="foot-note">{{ EVALUATION_TEXT.evidenceNote }}</p>
          </details>
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
