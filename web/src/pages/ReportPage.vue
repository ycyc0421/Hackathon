<script setup>
/**
 * 报告页：本次检查的汇总与待处理问题。
 *
 * 与差异页结果同源（都读同一个 task），因此不会出现两边数字不一致。
 * 导出功能未实现：契约第四节第 9 项未定导出由哪个接口提供。
 */
import { computed, inject } from 'vue'
import { formatTime, formatDuration, riskType, severity, processStatus } from '../api/formatters.js'
import StatusBadge from '../components/StatusBadge.vue'
import NoticeBar from '../components/NoticeBar.vue'
import SkeletonBlock from '../components/SkeletonBlock.vue'
import EmptyState from '../components/EmptyState.vue'

const task = inject('task')
const isRunning = inject('isRunning')
/** 跨页导航：跳差异页对应条目。App 层提供 */
const navigate = inject('navigate')

const summary = computed(() => task.value?.summary ?? null)

/** 需要处理的条目：不一致、部分缺失、未校验、无法比对 */
const issues = computed(() => {
  const list = task.value?.comparisons ?? []
  return list.filter((c) => !['MATCH', 'SINGLE_SOURCE'].includes(c.status))
})

const matched = computed(() => (task.value?.comparisons ?? []).filter((c) => c.status === 'MATCH'))

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
 * 「没有风险提示」正向空状态仅在有成功结果且确实零风险时显示。
 * FAILED 时不显示——任务失败与"没有风险"是两回事（AGENTS.md 降级原则）。
 */
const showNoRisk = computed(
  () => task.value && task.value.status !== 'FAILED' && (task.value.risks ?? []).length === 0
)

const duration = computed(() =>
  task.value ? formatDuration(task.value.created_at, task.value.finished_at) : null
)

/**
 * 检查概要的开头结论：把统计数字串成一句话，让读者先知道"要不要处理"。
 * - summary 为 null（或任务进行中/失败）时整段不显示——不替后端下结论；
 * - PARTIAL 必须带"不完整"前缀，不能被读成通过；
 * - 为 0 的类别跳过不念；风险提示为 0 时只有确实零问题才说"未发现风险"。
 */
const conclusion = computed(() => {
  if (!task.value || !summary.value || task.value.status === 'FAILED') return null
  const s = summary.value

  const prefix =
    task.value.status === 'PARTIAL'
      ? `${failedDocs.value.length} 份文件未能处理，本报告基于不完整结果。`
      : ''

  const problemParts = []
  if (s.conflict_count > 0) problemParts.push(`${s.conflict_count} 处不一致`)
  if (s.missing_count > 0) problemParts.push(`${s.missing_count} 处部分缺失`)
  if (s.unrecognized_count > 0) problemParts.push(`${s.unrecognized_count} 处无法比对`)

  if (!problemParts.length) {
    // 无问题：只有零风险才能说"未发现风险"，有风险必须念出来（零问题也可能有风险）
    const tail = s.risk_count > 0 ? `，另有 ${s.risk_count} 条风险提示需要人工查看` : '，未发现风险提示'
    return `${prefix}${s.document_count} 份文件、${s.field_count} 个字段全部一致${tail}。`
  }

  const riskPart = s.risk_count > 0 ? `，另有 ${s.risk_count} 条风险提示` : ''
  return `${prefix}发现 ${problemParts.join('、')}${riskPart}——需要人工复核。`
})

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

    <NoticeBar
      v-else-if="!task"
      tone="info"
      title="尚无检查结果"
      detail="请先在「上传」页创建一次检查。"
    />

    <template v-else>
      <!-- 未完成 / 失败的检查不得呈现为"通过" -->
      <NoticeBar
        v-if="task.status === 'FAILED'"
        tone="bad"
        title="检查失败，无报告可出"
        detail="未产生任何比对结果。"
      />
      <NoticeBar
        v-else-if="task.status === 'PARTIAL'"
        tone="warn"
        title="报告基于不完整的结果"
        :detail="`${failedDocs.length} 份文件未能处理成功，其数据未参与比对。`"
      />

      <section class="card">
        <h2 class="card-title">检查概要</h2>

        <!-- 结论先行：一段话回答"这次检查要不要处理"。summary 缺失时不显示，不替后端下结论 -->
        <p v-if="conclusion" class="report-conclusion">{{ conclusion }}</p>

        <dl class="meta-grid">
          <div><dt>任务编号</dt><dd>{{ task.task_id }}</dd></div>
          <div><dt>目的国</dt><dd>{{ task.input?.destination_country_name || task.input?.destination_country || '—' }}</dd></div>
          <div><dt>创建时间</dt><dd>{{ formatTime(task.created_at) }}</dd></div>
          <div v-if="duration"><dt>耗时</dt><dd>{{ duration }}</dd></div>
        </dl>

        <div v-if="summary" class="stat-row">
          <div class="stat"><span class="stat-num">{{ summary.document_count }}</span><span class="stat-label">文件</span></div>
          <div class="stat"><span class="stat-num">{{ summary.field_count }}</span><span class="stat-label">抽取字段</span></div>
          <div class="stat" :class="{ alert: summary.conflict_count > 0 }">
            <span class="stat-num">{{ summary.conflict_count }}</span><span class="stat-label">不一致</span>
          </div>
          <div class="stat" :class="{ warn: summary.missing_count > 0 }">
            <span class="stat-num">{{ summary.missing_count }}</span><span class="stat-label">部分缺失</span>
          </div>
          <div class="stat" :class="{ warn: summary.unrecognized_count > 0 }">
            <span class="stat-num">{{ summary.unrecognized_count }}</span><span class="stat-label">无法比对</span>
          </div>
          <div class="stat"><span class="stat-num">{{ summary.risk_count }}</span><span class="stat-label">风险提示</span></div>
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
            <!-- 失败原因必须能看到，不能随压缩丢失 -->
            <span v-if="d.error_message" class="doc-chip-error">{{ d.error_message }}</span>
          </li>
        </ul>
      </section>

      <section class="card">
        <h2 class="card-title">需要处理的条目 <span class="title-num">{{ issues.length }}</span></h2>

        <ul v-if="issues.length" class="issue-list">
          <li v-for="c in issues" :key="c.comparison_id" class="issue-item">
            <div class="issue-head">
              <span class="issue-label">{{ c.label }}</span>
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
        <EmptyState
          v-else
          tone="ok"
          icon="✅"
          title="没有需要人工处理的条目"
          detail="所有字段在各文件间一致。"
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

      <!-- 有成功结果且确实零风险时给出正向反馈，避免显示成空白表格 -->
      <EmptyState
        v-if="showNoRisk"
        tone="ok"
        icon="✅"
        title="没有风险提示"
        detail="本次检查未发现需要提示的风险项。"
      />

      <section v-if="task.errors?.length" class="card">
        <h2 class="card-title">错误记录</h2>
        <ul class="err-list">
          <li v-for="(e, i) in task.errors" :key="i" class="err-item">
            <span class="err-code">{{ e.code }}</span>
            <span class="err-msg">{{ e.message }}</span>
          </li>
        </ul>
      </section>

      <NoticeBar
        tone="info"
        title="报告导出尚未实现"
        detail="导出由哪个接口提供、采用何种格式尚未确认，因此本页暂不提供导出按钮。"
      />
    </template>
  </div>
</template>
