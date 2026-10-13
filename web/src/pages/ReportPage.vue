<script setup>
/**
 * 报告页：本次检查的汇总与待处理问题。
 *
 * 与差异页结果同源（都读同一个 task），因此不会出现两边数字不一致。
 * 真实任务可导出报告并创建人工修正版本。
 */
import { computed, inject } from 'vue'
import { formatTime, formatDuration, riskType, severity, processStatus, taskStatus } from '../api/formatters.js'
import { buildConclusion, comparisonCounts } from '../utils/reportConclusion.js'
import { needsReview } from '../utils/needsReview.js'
import StatusBadge from '../components/StatusBadge.vue'
import NoticeBar from '../components/NoticeBar.vue'
import SkeletonBlock from '../components/SkeletonBlock.vue'
import WorkflowActions from '../components/WorkflowActions.vue'
import DocumentNumbers from '../components/DocumentNumbers.vue'

const task = inject('task')
const isRunning = inject('isRunning')
/** 轮询/请求失败信息。缓存 task 还在时不把它当完成报告，必须叠加提示 */
const taskError = inject('taskError', null)
/** 跨页导航：跳差异页对应条目。App 层提供 */
const navigate = inject('navigate')

const summary = computed(() => task.value?.summary ?? null)

/** 终态：只有到达终态的任务才允许出现正向结论与成功式空状态 */
const TERMINAL_STATUSES = ['COMPLETED', 'PARTIAL', 'FAILED']
const isTerminal = computed(() => task.value && TERMINAL_STATUSES.includes(task.value.status))

/**
 * 需要处理的条目：与差异页「需关注」同一口径（needsReview）——
 * 问题状态之外，MATCH 但含 LOW_CONFIDENCE 取值（请核对）的也在列。
 */
const issues = computed(() => {
  const list = task.value?.comparisons ?? []
  return list.filter(needsReview)
})

/** 「另有 N 个字段一致」脚注：已列入问题条目的 MATCH（含请核对取值）不再重复计数 */
const matched = computed(
  () => (task.value?.comparisons ?? []).filter((c) => c.status === 'MATCH' && !needsReview(c))
)

const failedDocs = computed(
  () =>
    task.value?.documents?.filter(
      (d) => d.process_status === 'FAILED' || d.process_status === 'UNSUPPORTED'
    ) ?? []
)

/** 未经规则校验的风险与规则命中的风险分开显示，可信度不同 */
const ruledRisks = computed(() => (task.value?.risks ?? []).filter((r) => r.rule_id))
const suggestedRisks = computed(() => (task.value?.risks ?? []).filter((r) => !r.rule_id))

/**
 * 「没有风险提示」正向空状态仅在到达终态、无请求错误且确实零风险时显示。
 * FAILED / 处理中 / 轮询失败都不算——任务失败与"没有风险"是两回事（AGENTS.md 降级原则）。
 */
const showNoRisk = computed(
  () =>
    isTerminal.value &&
    !taskError?.value &&
    task.value.status !== 'FAILED' &&
    (task.value.risks ?? []).length === 0
)

/**
 * 文件自身编号（document_no）的待核对状态。
 *
 * document_no 没有对应的比较项，但 LOW_CONFIDENCE / UNRECOGNIZED /
 * NORMALIZE_FAILED / MISSING_IN_DOC 仍需在文件清单提示；存在这些提示时，
 * 报告不能笼统写"没有需要人工处理的条目"。比较计数保持原样，不为此伪造
 * comparisons。NOT_IN_DOC 与缺少整个可选字段不算异常，不计入。
 */
const DOCNO_ATTENTION = ['LOW_CONFIDENCE', 'UNRECOGNIZED', 'NORMALIZE_FAILED', 'MISSING_IN_DOC']
const docNoAttentionCount = computed(() => {
  const exts = task.value?.extractions ?? []
  let n = 0
  for (const e of exts) {
    for (const f of e?.fields ?? []) {
      if (
        f?.field_key === 'document_no' &&
        (f.item_id ?? null) === null &&
        (f.line_no ?? null) === null &&
        DOCNO_ATTENTION.includes(f.status)
      )
        n += 1
    }
  }
  return n
})

/** 「没有需要人工处理的条目」成功式空状态：仅终态成功、无请求错误且无编号待核对提示时出现 */
const showNoIssues = computed(
  () =>
    isTerminal.value &&
    !taskError?.value &&
    task.value.status !== 'FAILED' &&
    issues.value.length === 0 &&
    docNoAttentionCount.value === 0
)

const duration = computed(() =>
  task.value ? formatDuration(task.value.created_at, task.value.finished_at) : null
)

/** comparisons 各状态条数，结论与概要都以它为准（不信 summary 的问题计数反推一致） */
const counts = computed(() => comparisonCounts(task.value?.comparisons))

/**
 * 检查概要的开头结论：把统计数字串成一句话，让读者先知道"要不要处理"。
 * 推导规则集中在 utils/reportConclusion.js：
 * 只有到达终态、且比对状态确实支持时才有正向结论；否则整段不显示——不替后端下结论。
 */
const conclusion = computed(() => {
  if (!task.value || !summary.value || taskError?.value) return null
  return buildConclusion({
    status: task.value.status,
    documentCount: summary.value.document_count,
    fieldCount: summary.value.field_count,
    riskCount: summary.value.risk_count,
    failedDocCount: failedDocs.value.length,
    counts: counts.value,
  })
})

/** 商品目录：item_id → 展示名。目录缺失或查不到时返回 null，降级不猜商品名 */
const itemNames = computed(
  () => new Map((task.value?.items ?? []).map((it) => [it.item_id, it.display_name]))
)

/** 问题条目的归属：整票字段 / 商品名 / null（无法确定时不显示，不猜） */
function issueScope(c) {
  if (c.item_id == null) return '整票字段'
  return itemNames.value.get(c.item_id) ?? null
}

/** 文件 chip 的色点按处理状态着色，复用状态文案表里的语义色 */
const docTone = (d) => processStatus(d.process_status).tone

const severityOf = severity
</script>

<template>
  <div class="page">
    <!-- 任务进行中且没有旧结果：按概要卡 + 统计行的形状占位 -->
    <template v-if="!task && isRunning">
      <section class="card" aria-hidden="true">
        <SkeletonBlock width="100px" height="18px" />
        <div class="skeleton-meta-grid">
          <SkeletonBlock v-for="i in 4" :key="i" height="36px" />
        </div>
        <div class="skeleton-stat-row">
          <SkeletonBlock v-for="i in 6" :key="i" height="52px" radius="md" />
        </div>
      </section>
      <section class="card" aria-hidden="true">
        <SkeletonBlock width="100px" height="18px" />
        <SkeletonBlock v-for="i in 3" :key="i" height="34px" />
      </section>
    </template>

    <!-- 轮询失败且没有任何任务数据：失败本身就是要呈现的状态 -->
    <NoticeBar
      v-else-if="!task && taskError"
      tone="bad"
      title="尚未取得检查结果"
      :detail="taskError.message"
    >
      <!-- 失败提示不能只给原因不给出口：直接引导回上传页重新检查 -->
      <button class="btn primary" @click="navigate.go('upload')">去上传页重新检查</button>
    </NoticeBar>

    <NoticeBar
      v-else-if="!task"
      tone="info"
      title="尚无检查结果"
      detail="请先在「上传」页创建一次检查。"
    >
      <!-- 空状态给出明确的下一步操作，而不是只提示一句说明 -->
      <button class="btn primary" @click="navigate.go('upload')">去上传页创建检查</button>
    </NoticeBar>

    <template v-else>
      <!-- 未完成 / 失败的检查不得呈现为"通过" -->
      <NoticeBar
        v-if="task.status === 'FAILED'"
        tone="bad"
        title="检查失败；可导出失败明细"
        detail="未产生任何比对结果，但可导出失败报告留档。"
      />
      <!-- 轮询中断但缓存还是中间状态：明确尚未取得最终结果，不把缓存当完成报告 -->
      <NoticeBar
        v-else-if="taskError && !isTerminal"
        tone="bad"
        title="尚未取得最终结果"
        :detail="`${taskError.message}。以下为最近一次查询到的中间状态，不是最终报告。`"
      />
      <!-- 处理中：即使有 task 对象也不给正向结论 -->
      <NoticeBar
        v-else-if="!isTerminal"
        tone="info"
        title="任务仍在处理中"
        detail="以下为中间状态，尚未产生最终结论；处理完成前不能视为通过。"
      />
      <NoticeBar
        v-else-if="task.status === 'PARTIAL'"
        tone="warn"
        title="报告基于不完整的结果"
        :detail="`${failedDocs.length} 份文件未能处理成功，其数据未参与比对。`"
      />

      <section class="card report-head" :class="conclusion ? `tone-${conclusion.tone}` : ''">
        <div class="report-kicker">
          <h2 class="card-title">检查概要</h2>
          <StatusBadge :status="taskStatus(task.status)" />
        </div>

        <!-- 结论先行：一段话回答"这次检查要不要处理"。summary 缺失时不显示，不替后端下结论。
             tone 与文案同源推导（utils/reportConclusion.js），结论条按 tone 上色 -->
        <p v-if="conclusion" class="report-conclusion" :class="`tone-${conclusion.tone}`">{{ conclusion.text }}</p>

        <dl class="meta-grid">
          <div><dt>任务编号</dt><dd>{{ task.task_id }}</dd></div>
          <div><dt>目的国</dt><dd>{{ task.input?.destination_country_name || task.input?.destination_country || '—' }}</dd></div>
          <div><dt>创建时间</dt><dd>{{ formatTime(task.created_at) }}</dd></div>
          <div v-if="duration"><dt>耗时</dt><dd>{{ duration }}</dd></div>
        </dl>

        <div v-if="summary" class="stat-row">
          <div class="stat"><span class="stat-num">{{ summary.document_count }}</span><span class="stat-label">文件</span></div>
          <div class="stat"><span class="stat-num">{{ summary.field_count }}</span><span class="stat-label">抽取字段</span></div>
          <div class="stat" :class="summary.conflict_count > 0 ? 'alert' : 'zero'">
            <span class="stat-num">{{ summary.conflict_count }}</span><span class="stat-label">不一致</span>
          </div>
          <div class="stat" :class="summary.missing_count > 0 ? 'warn' : 'zero'">
            <span class="stat-num">{{ summary.missing_count }}</span><span class="stat-label">部分缺失</span>
          </div>
          <div class="stat" :class="summary.unrecognized_count > 0 ? 'warn' : 'zero'">
            <span class="stat-num">{{ summary.unrecognized_count }}</span><span class="stat-label">无法比对</span>
          </div>
          <div class="stat" :class="summary.risk_count > 0 ? '' : 'zero'"><span class="stat-num">{{ summary.risk_count }}</span><span class="stat-label">风险提示</span></div>
        </div>
      </section>

      <section class="card">
        <h2 class="card-title">文件清单</h2>
        <ul class="doc-chips">
          <li v-for="d in task.documents" :key="d.file_id" class="doc-chip">
            <span class="doc-chip-main">
              <span class="doc-chip-dot" :class="`tone-${docTone(d)}`" aria-hidden="true"></span>
              <span class="doc-chip-name">{{ d.file_name }}</span>
              <span class="doc-chip-type">{{ d.doc_type || '类型未识别' }}</span>
            </span>
            <!-- 该文件自身的单据编号（document_no）：按 file_id 关联抽取层，无编号时整行隐藏 -->
            <DocumentNumbers :document="d" :extractions="task.extractions" />
            <!-- 失败原因必须能看到，不能随压缩丢失 -->
            <span v-if="d.error_message" class="doc-chip-error">{{ d.error_message }}</span>
          </li>
        </ul>
      </section>

      <section class="card">
        <h2 class="card-title">需要处理的条目 <span class="title-num">{{ issues.length }}</span></h2>

        <!-- 编号待核对不计入上方比较条目数（document_no 无比较项，不伪造 comparisons），
             单独一行提示；此时不再显示"没有需要人工处理的条目" -->
        <NoticeBar
          v-if="issues.length === 0 && docNoAttentionCount > 0"
          tone="warn"
          :title="`有 ${docNoAttentionCount} 份文件的自身编号需要人工核对`"
          detail="编号问题已在上方文件清单中标注；比对条目计数不受影响。"
        />

        <ul v-if="issues.length" class="issue-list">
          <li v-for="c in issues" :key="c.comparison_id" class="issue-item" :class="`sev-${severityOf(c.severity).tone}`">
            <div class="issue-head">
              <span class="issue-label">{{ c.label }}</span>
              <!-- 商品归属：多品名时问题条目必须能区分属于哪个商品；查不到目录时不猜 -->
              <span v-if="issueScope(c)" class="issue-scope">{{ issueScope(c) }}</span>
              <StatusBadge :status="severityOf(c.severity)" />
            </div>
            <div class="issue-values">
              <span v-for="v in c.values" :key="v.file_id" class="issue-value">
                {{ v.file_name.split('.')[0] }}：
                <strong>{{ v.normalized_value ?? '未取得' }}</strong>
              </span>
            </div>
            <p v-if="c.note" class="issue-note">{{ c.note }}</p>
            <!-- 后端的处理建议（可选）。建议不代替比对结论，用次要文本呈现 -->
            <p v-if="c.suggested_action" class="issue-note">建议：{{ c.suggested_action }}</p>
            <div class="issue-foot">
              <button class="link-btn" @click="navigate.go('diff', c.comparison_id)">在差异页查看 →</button>
            </div>
          </li>
        </ul>
        <!-- 成功式确认只在终态成功时出现；处理中/失败/轮询中断都不能显示"没有问题"。
             正向确认收敛为一条细窄提示条，不用居中大空状态（DESIGN.md 通过态收敛原则） -->
        <NoticeBar
          v-else-if="showNoIssues"
          tone="ok"
          :title="showNoRisk ? '没有需要人工处理的条目，也未发现风险提示' : '没有需要人工处理的条目'"
        />

        <p v-if="matched.length" class="foot-note">
          另有 {{ matched.length }} 个字段在各文件间一致，未列出。
        </p>
      </section>

      <section v-if="ruledRisks.length" class="card">
        <h2 class="card-title">依据规则的提示</h2>
        <ul class="risk-list">
          <li v-for="r in ruledRisks" :key="r.risk_id" class="risk-item">
            <div class="risk-head">
              <span class="risk-type">{{ riskType(r.type) }}</span>
              <StatusBadge :status="severityOf(r.severity)" />
            </div>
            <div class="risk-title">{{ r.title }}</div>
            <p class="risk-detail">{{ r.detail }}</p>
            <div class="risk-foot">规则 {{ r.rule_id }}<template v-if="r.rule_source"> · {{ r.rule_source }}</template></div>
            <!-- 后端的处理建议（可选）。建议不代替结论，用次要文本呈现 -->
            <p v-if="r.suggested_action" class="risk-detail">建议：{{ r.suggested_action }}</p>
          </li>
        </ul>
      </section>

      <section v-if="suggestedRisks.length" class="card">
        <h2 class="card-title">未经规则校验的提示</h2>
        <p class="card-sub">以下提示没有对应的规则编号，仅供参考，不作为合规结论。</p>
        <ul class="risk-list">
          <li v-for="r in suggestedRisks" :key="r.risk_id" class="risk-item suggested">
            <div class="risk-head">
              <span class="risk-type">{{ riskType(r.type) }}</span>
              <StatusBadge :status="severityOf(r.severity)" />
            </div>
            <div class="risk-title">{{ r.title }}</div>
            <p class="risk-detail">{{ r.detail }}</p>
            <!-- 后端的处理建议（可选）。建议不代替结论，用次要文本呈现 -->
            <p v-if="r.suggested_action" class="risk-detail">建议：{{ r.suggested_action }}</p>
          </li>
        </ul>
      </section>

      <section v-if="task.errors?.length" class="card">
        <h2 class="card-title">错误记录</h2>
        <ul class="err-list">
          <li v-for="(e, i) in task.errors" :key="i" class="err-item">
            <span class="err-code">{{ e.code }}</span>
            <span class="err-msg">{{ e.message }}</span>
          </li>
        </ul>
      </section>

      <WorkflowActions />
    </template>
  </div>
</template>
