/**
 * 导出报告：把报告契约 v2 的 `view=content` 内容渲染成一份自包含的 HTML 文档。
 *
 * 职责边界（issue #51）：后端提供结构化内容，前端负责排版、布局与打印呈现。
 * 后端 `format=html` 已返回 410，导出的 HTML 由这里生成。
 *
 * 三条硬约束，都来自 `AGENTS.md` 的降级原则与 issue #51 的验收：
 *
 * 1. **不把"没查到"呈现为"通过"**。未校验、仅一份文件、无法比对、未核实、
 *    处理失败都必须各自看得见；结论复用报告页的 `buildConclusion`，
 *    口径与页面完全一致（同一份结论的两种呈现，不允许一边说 3 处一边说 2 处）。
 * 2. **不把内部标识当展示文案**。`item_001`、`COMMERCIAL_INVOICE`、`CONFLICT`
 *    这些是机器接口的关联键与枚举，展示一律走 `labels.js` 的中文表；
 *    商品名用后端给的 `label`，字段名用后端给的 `label`。
 * 3. **缺失就留空**。没有可信度不显示可信度，没有定位信息不显示页码，
 *    历史规则版本没记录就写"未记录"，不用当前版本回填、不填任何默认值。
 *
 * 输出是纯字符串，不碰 DOM——便于在 node 里直接单测（见 tests/report-document.test.mjs）。
 */

import { formatValue, formatTime, formatDuration } from '../api/formatters.js'
import {
  lookup,
  DOC_TYPE,
  ALIGNMENT_STATUS,
  ALIGNMENT_BASIS,
  VERIFICATION_STATUS,
  EXECUTION_VERSION_STATUS,
  LIMITATION_TEXT,
  SOURCE_STATUS,
  SOURCE_REVIEW_STATUS,
  TASK_STATUS,
  PROCESS_STATUS,
  FIELD_STATUS,
  COMPARISON_STATUS,
  SEVERITY,
  ERROR_LEVEL,
  RISK_TYPE,
} from '../api/labels.js'
import { buildConclusion, comparisonCounts } from '../utils/reportConclusion.js'
import { needsReview } from '../utils/needsReview.js'
import { REPORT_CSS } from './styles.js'

/* --------------------------------------------------------------------------
   基础工具
   -------------------------------------------------------------------------- */

/**
 * HTML 转义。报告里的每一个值都来自后端，包含用户上传文件名、OCR 原文和
 * 商品名——**一律当不可信文本**。多品名夹具里的商品名就带 `<b>TEST</b>`，
 * 这不是理论风险：不转义就会被当成标签渲染，报告里凭空多出格式。
 */
export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c])
}

/** 空值统一显示为破折号；0 与空串是有效值，不能被吃掉 */
function text(value) {
  if (value === null || value === undefined || value === '') return '<span class="muted">—</span>'
  return escapeHtml(value)
}

/** 纯文本版空值处理，用于拼进属性或已有转义结构的地方 */
function plain(value, fallback = '—') {
  if (value === null || value === undefined || value === '') return fallback
  return String(value)
}

/** 状态徽章。文案与配色来自 labels.js，页面与导出件同一套 */
function badge(status) {
  if (!status?.text) return ''
  return `<span class="badge tone-${escapeHtml(status.tone)}">${escapeHtml(status.text)}</span>`
}

/** 单证类型：契约枚举 → 中文。查不到时不把英文枚举甩给用户 */
const docTypeText = (v) => (v ? lookup(DOC_TYPE, v, '类型未识别').text : '类型未识别')

/**
 * 字段状态标签。`EXTRACTED` 在 labels.js 里 text 为空（正常值不挂徽章），
 * 这里返回空串让调用方整块不渲染。
 */
const fieldStatusBadge = (v) => badge(lookup(FIELD_STATUS, v))

/**
 * 渲染一个抽取字段的有效值。
 *
 * `ExtractedField` 契约里没有 `value_type`（只有比对项才有），所以只能按值的
 * 实际类型选格式：数字走千分位，其余按字符串。这是纯展示层的推断，
 * 不改变值本身；拿不准时按字符串原样输出，不会把文本当数字处理。
 */
function fieldValue(field) {
  const value = field?.normalized_value ?? field?.raw_value
  const type = typeof field?.normalized_value === 'number' ? 'NUMBER' : 'STRING'
  const shown = formatValue(value, type, field?.unit)
  return `${escapeHtml(shown.main)}${field?.unit ? ` ${escapeHtml(field.unit)}` : ''}`
}

/** 页面外壳。lang 与 charset 显式给出，导出件要能离线打开 */
function page({ title, body }) {
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="cross-border doc check">
<title>${escapeHtml(title)}</title>
<style>${REPORT_CSS}</style>
</head>
<body>
${body}
</body>
</html>
`
}

/* --------------------------------------------------------------------------
   各区块
   -------------------------------------------------------------------------- */

/** 统计小卡。零值的问题计数收敛为虚线灰字，不抢"没问题"的语义 */
function statCard(num, label, kind = '') {
  return `<div class="stat ${kind}"><span class="stat-num">${escapeHtml(num)}</span><span class="stat-label">${escapeHtml(label)}</span></div>`
}

function notice(tone, title, detail) {
  return `<div class="notice tone-${tone}">
<p class="notice-title">${escapeHtml(title)}</p>
${detail ? `<p class="notice-detail">${escapeHtml(detail)}</p>` : ''}
</div>`
}

function card(title, body, { sub = '', num = null } = {}) {
  const heading = num === null ? escapeHtml(title) : `${escapeHtml(title)} <span class="title-num">${escapeHtml(num)}</span>`
  return `<section class="card">
<h2 class="card-title">${heading}</h2>
${sub ? `<p class="card-sub">${escapeHtml(sub)}</p>` : ''}
${body}
</section>`
}

/**
 * 报告头：状态色带 + 标题 + 结论 + 元信息 + 统计行。
 *
 * 结论段只在 `buildConclusion` 给得出结论时渲染——它内部已经保证了
 * 未校验/单一来源/非终态不会被概括成"全部一致"。
 */
function header(content) {
  const { task } = content
  const summary = task.summary ?? {}
  /**
   * 问题计数一律用 comparisonCounts 现算，而不是读 summary 里的同名计数。
   *
   * 两者理论上一致，但 summary 是原任务的统计、counts 是投影后 comparisons 的
   * 统计，一旦不一致就会出现"结论说 3 处不一致、统计卡说 2 处"这种自相矛盾的
   * 报告。结论段（buildConclusion）本来就吃 counts，统计卡跟着它走，
   * 导出的这份文件内部必定自洽。文件数/字段数/风险数没有这个问题，仍读 summary。
   */
  const counts = comparisonCounts(content.comparisons)
  const failedDocs = (content.documents ?? []).filter(
    (d) => d.process_status === 'FAILED' || d.process_status === 'UNSUPPORTED'
  )
  const conclusion = buildConclusion({
    status: task.status,
    documentCount: summary.document_count ?? 0,
    fieldCount: summary.field_count ?? 0,
    riskCount: summary.risk_count ?? 0,
    failedDocCount: failedDocs.length,
    counts,
  })
  const duration = formatDuration(task.created_at, task.finished_at)

  const meta = [
    ['任务编号', task.task_id, true],
    ['目的国', task.input?.destination_country_name || task.input?.destination_country, false],
    ['创建时间', formatTime(task.created_at), false],
    ['完成时间', task.finished_at ? formatTime(task.finished_at) : null, false],
    ['耗时', duration, false],
    ['报告生成时间', formatTime(content.generated_at), false],
  ].filter(([, v]) => v !== null && v !== undefined && v !== '')

  /**
   * 顶部色带的颜色。
   *
   * 结论存在时跟结论同源（不出现"坏消息配绿条"的错位）。结论为 null 只发生在
   * 非终态或 counts 缺失时，而导出只在终态可用——所以这里主要是给 FAILED 兜底：
   * 一次失败的检查必须有自己的颜色，不能退回中性灰，那样和"没有结论"长得一样。
   */
  const tone = conclusion?.tone ?? (task.status === 'FAILED' ? 'bad' : task.status === 'PARTIAL' ? 'warn' : null)

  return `<header class="report-head${tone && tone !== 'neutral' ? ` tone-${tone}` : ''}">
<div class="report-kicker">
<div>
<h1 class="report-title">单证检查报告</h1>
<p class="report-sub">跨境物流单证智能转换与合规校验 · 结构化检查结果</p>
</div>
${badge(lookup(TASK_STATUS, task.status))}
</div>
${conclusion ? `<p class="report-conclusion tone-${conclusion.tone}">${escapeHtml(conclusion.text)}</p>` : ''}
<dl class="meta-grid">
${meta.map(([k, v, mono]) => `<div><dt>${escapeHtml(k)}</dt><dd${mono ? ' class="mono"' : ''}>${text(v)}</dd></div>`).join('\n')}
</dl>
<div class="stat-row">
${statCard(summary.document_count ?? 0, '文件')}
${statCard(summary.field_count ?? 0, '抽取字段')}
${statCard(counts.conflict, '不一致', counts.conflict > 0 ? 'alert' : 'zero')}
${statCard(counts.missing, '部分缺失', counts.missing > 0 ? 'warn' : 'zero')}
${statCard(counts.unrecognized, '无法比对', counts.unrecognized > 0 ? 'warn' : 'zero')}
${statCard(counts.unchecked, '未校验', counts.unchecked > 0 ? 'warn' : 'zero')}
${statCard(counts.single, '仅一份文件', counts.single > 0 ? '' : 'zero')}
${statCard(summary.risk_count ?? 0, '风险提示', (summary.risk_count ?? 0) > 0 ? '' : 'zero')}
</div>
</header>`
}

/**
 * 文件清单。
 *
 * 展示单据自身的编号（identifiers）与未被交叉比对覆盖的补充字段（fields）——
 * 收发货人、合同号、集装箱号、港口这些只在单份文件里出现的业务信息，
 * 不因为缺少比对就从报告里消失（#51 的 F 侧交付范围）。
 */
function documentsSection(content) {
  if (!content.documents?.length) return ''

  const rows = content.documents.map((d) => {
    const ids = d.identifiers ?? []
    const fields = d.fields ?? []
    const extras = [
      ...ids.map((f) => ({ ...f, kind: '编号' })),
      ...fields.map((f) => ({ ...f, kind: '' })),
    ]
    const extraHtml = extras.length
      ? `<ul class="id-list">${extras.map((f) => `<li><span class="id-label">${escapeHtml(f.label)}</span><span class="id-value">${fieldValue(f)}</span>${fieldStatusBadge(f.status)}</li>`).join('')}</ul>`
      : ''

    return `<tr>
<td>
<span class="doc-name">${escapeHtml(d.file_name)}</span>
<div class="doc-meta">${escapeHtml(docTypeText(d.doc_type))}${d.page_count ? ` · ${escapeHtml(d.page_count)} 页` : ''}${d.file_type ? ` · ${escapeHtml(d.file_type)}` : ''}</div>
${extraHtml}
</td>
<td class="col-narrow">${badge(lookup(PROCESS_STATUS, d.process_status))}</td>
<td>${d.error_message ? `<span class="doc-error">${escapeHtml(d.error_message)}</span>` : '<span class="muted">—</span>'}</td>
</tr>`
  }).join('\n')

  return card('文件清单与逐文件状态', `<table class="table">
<thead><tr><th>文件</th><th>处理状态</th><th>失败原因</th></tr></thead>
<tbody>
${rows}
</tbody>
</table>`, {
    sub: '补充字段是该文件独有、未参与交叉比对的信息，一并留档。',
  })
}

/**
 * 比对条目里的一个取值：有效值 + 单位 + 原文证据 + 字段状态。
 *
 * 原文证据来自后端投影的 `values[].evidence`（唯一同文件同字段同行的片段）；
 * 后端定位不到时 `status=UNAVAILABLE`，此时如实显示"未定位到原文"，
 * 不猜一条、也不跨行取证。页码只在后端给出时才显示。
 */
function valueRow(v, comparison) {
  const shown = formatValue(v.normalized_value, comparison.value_type, comparison.unit)
  const evidence = v.evidence ?? {}
  const rawText = evidence.raw_text
  const located = evidence.status === 'LOCATED' && rawText

  const bits = [
    `<span class="value-file">${escapeHtml(v.file_name)}</span>`,
    `<span class="value-main">${escapeHtml(shown.main)}</span>`,
    shown.sub ? `<span class="value-unit">${escapeHtml(shown.sub)}</span>` : '',
    fieldStatusBadge(v.field_status),
    v.page ? `<span class="value-unit">第 ${escapeHtml(v.page)} 页</span>` : '',
  ].filter(Boolean)

  const rawLine = located
    ? `<span class="value-raw">${escapeHtml(rawText)}</span>`
    : '<span class="value-raw muted">未定位到原文片段</span>'

  return `<div class="value-row">${bits.join('')}</div>${rawLine}`
}

/** 一条比对条目（问题条目与其余条目共用同一渲染） */
function comparisonItem(c, { scopeName = null, tone = 'bad' } = {}) {
  const values = (c.values ?? []).map((v) => valueRow(v, c)).join('\n')
  return `<li class="issue-item sev-${escapeHtml(tone)}">
<div class="item-head">
<span class="item-label">${escapeHtml(c.label)}</span>
${scopeName ? `<span class="item-scope">${escapeHtml(scopeName)}</span>` : ''}
${badge(lookup(SEVERITY, c.severity, '提示'))}
${badge(lookup(COMPARISON_STATUS, c.status))}
</div>
<div class="value-block">
${values}
</div>
${c.note ? `<p class="item-note">${escapeHtml(c.note)}</p>` : ''}
${c.rule_id ? `<div class="item-foot">规则 ${escapeHtml(c.rule_id)}</div>` : ''}
</li>`
}

/** severity → 左色条 tone，与徽章同一口径 */
const severityTone = (s) => lookup(SEVERITY, s, '提示').tone

/**
 * 需要人工处理的条目。
 *
 * 口径与报告页、差异页完全一致（`needsReview`）：问题状态之外，
 * 含 LOW_CONFIDENCE 取值的 MATCH 也算——只看状态集合会漏掉"归一后一致、
 * 但原文可信度低"这一类，用户处理完列表≠处理完全部复核要求。
 */
function issuesSection(content) {
  const itemNames = new Map((content.items ?? []).map((it) => [it.item_id, it.label]))
  const issues = (content.comparisons ?? []).filter(needsReview)

  if (!issues.length) {
    const hasAny = (content.comparisons ?? []).length > 0
    /**
     * 空列表**不是**通过。
     *
     * 三种情况都不能用绿色的"没有需要人工处理的条目"收尾：
     * - 本次压根没产生比对条目（全部文件处理失败就是这种）；
     * - 检查本身失败了——在失败的报告里放一条绿色确认，读起来就是"没问题"；
     * - 任务只是部分完成，剩下的文件根本没参与比对。
     * 只有真正跑完、有比对条目、且一条都不用复核时，才给绿色。
     */
    const failed = content.task?.status === 'FAILED'
    const partial = content.task?.status === 'PARTIAL'
    if (!hasAny) {
      return card('需要人工处理的条目', notice(
        failed ? 'bad' : 'warn',
        '本次未产生任何比对条目',
        '没有比对条目不等于没有问题：请核对上方文件清单中的处理状态与失败原因。'
      ))
    }
    if (failed || partial) {
      return card('需要人工处理的条目', notice(
        'warn',
        '已产生的比对条目中没有需要人工处理的条目',
        partial
          ? '但本报告基于不完整结果，未成功处理的文件没有参与比对，不能据此认为整票无问题。'
          : '但本次检查失败，该列表不构成通过结论。'
      ))
    }
    return card('需要人工处理的条目', notice('ok', '没有需要人工处理的条目'))
  }

  const list = issues.map((c) => comparisonItem(c, {
    scopeName: c.item_id != null ? itemNames.get(c.item_id) ?? null : '整票字段',
    tone: severityTone(c.severity),
  })).join('\n')

  return card('需要人工处理的条目', `<ul class="item-list">
${list}
</ul>`, { num: issues.length })
}

/**
 * 其余比对结果：一致 / 仅一份文件提供。
 *
 * 两类必须分开：`SINGLE_SOURCE` 只有一份文件给出该字段，**没有可交叉比对的对象**，
 * 与"两份文件都写了且一致"不是一回事。合并计数会让读者以为覆盖更全。
 */
function remainingSection(content) {
  const itemNames = new Map((content.items ?? []).map((it) => [it.item_id, it.label]))
  const rest = (content.comparisons ?? []).filter((c) => !needsReview(c))
  const matched = rest.filter((c) => c.status === 'MATCH')
  const single = rest.filter((c) => c.status === 'SINGLE_SOURCE')

  if (!matched.length && !single.length) return ''

  const scopeOf = (c) => (c.item_id != null ? itemNames.get(c.item_id) ?? null : '整票')

  // 先拼纯文本再统一转义一次。逐段 escapeHtml 后再拼、外层又转义一遍，
  // 会把 `&amp;` 变成 `&amp;amp;` 直接显示出来——原文里带 & 的商品名很常见。
  //
  // 归属 pill 紧跟字段名（而不是跟在取值后面）：取值动辄两三份文件拼一长串，
  // pill 放最后会被挤到下一行单独占位，读起来像是另一个条目的开头。
  const listOf = (rows) => `<ul class="plain-list">
${rows.map((c) => {
    const values = (c.values ?? []).map((v) => {
      const shown = formatValue(v.normalized_value, c.value_type, c.unit)
      return `${v.file_name} ${shown.main}${shown.sub ? ` ${shown.sub}` : ''}`
    })
    return `<li><span class="plain-key">${escapeHtml(c.label)}</span><span class="item-scope">${escapeHtml(plain(scopeOf(c), '整票'))}</span><span class="plain-value">${escapeHtml(values.join(' · '))}</span></li>`
  }).join('\n')}
</ul>`

  const blocks = []
  if (matched.length) {
    blocks.push(`<p class="card-sub">各文件取值一致（${matched.length} 条）</p>${listOf(matched)}`)
  }
  if (single.length) {
    blocks.push(`<p class="card-sub">仅一份文件提供、无法交叉比对（${single.length} 条）——不代表这些字段正确</p>${listOf(single)}`)
  }

  return card('其余比对结果', blocks.join('\n'))
}

/**
 * 风险提示。规则命中的风险与"模型建议、未经规则校验"的风险**分开两张卡**：
 * 两者的可信度不同，混在一起会让人以为后者也过了规则。
 *
 * 后端已把固定的未核实前后缀拆进 `rule_context`，这里按结构化字段重新组织，
 * 不再重复堆叠免责声明（#51 第 6 点）。
 */
/**
 * 适用条件（`rule_context.applicability`）。
 *
 * 后端给的是一个**机器结构**：键是 `hs_prefix_is_candidate_only`、
 * `required_facts` 这类英文标识，值是布尔或事实代码。直接 `JSON.stringify`
 * 丢进报告，等于把内部标识当展示文案——正是 issue #51 第 3 点点名的问题。
 *
 * 前端不能自建"英文键 → 中文名"的映射表（`AGENTS.md`：字段中文名一律读后端的
 * label，前端不维护映射）。所以这里只挑出**本身就能读**的部分：
 * `document_version` 是人写的说明文本，原样显示；其余布尔与代码列表只用于
 * 提示"还有未确认的适用条件"，具体内容让读者去规则定义里查。
 *
 * 结果是：报告不泄露内部键名，也不假装已经把适用条件讲清楚了。
 */
function applicabilityNote(applicability) {
  if (!applicability || typeof applicability !== 'object') return ''

  const parts = []
  if (typeof applicability.document_version === 'string' && applicability.document_version.trim()) {
    parts.push(escapeHtml(applicability.document_version))
  }

  // 有布尔/数组型条件时，不逐条翻译，只如实说明"存在需要人工确认的条件"
  const hasMachineConditions = Object.entries(applicability).some(
    ([key, value]) => key !== 'document_version' && (typeof value === 'boolean' || Array.isArray(value))
  )
  if (hasMachineConditions) {
    parts.push('该规则另有适用条件需要人工确认，详见规则定义。')
  }

  if (!parts.length) return ''
  return `<p class="item-note">适用条件：${parts.join('；')}</p>`
}

/**
 * 风险条目里"关联来源"的展示名。
 *
 * `rule_context.source_ids` 是规则与来源目录之间的关联键（`EU-FCM-LEGISLATION`
 * 这类），对读者没有意义。同一份报告的 provenance.sources 里已经有这些来源的
 * 机构名，所以在这里翻译过去；目录里没有的（例如规则指向了本次未关联的来源）
 * 才退回显示原始 id——宁可显示 id，也不假装知道它是什么。
 */
function sourceLabel(sourceId, sourceNames) {
  const name = sourceNames.get(sourceId)
  return name ? `${name}（${sourceId}）` : sourceId
}

function riskItem(r, itemNames, sourceNames) {
  const ctx = r.rule_context ?? {}
  const verification = ctx.verification_status ? lookup(VERIFICATION_STATUS, ctx.verification_status) : null
  const scopeNames = (r.related_item_ids ?? []).map((id) => itemNames.get(id)).filter(Boolean)
  const sourceIds = ctx.source_ids ?? []

  const foot = [
    r.rule_id ? `规则 ${r.rule_id}` : null,
    r.rule_source ? `来源：${r.rule_source}` : null,
    r.destination_country ? `目的国 ${r.destination_country}` : null,
    scopeNames.length ? `涉及商品：${scopeNames.join('、')}` : null,
  ].filter(Boolean)

  return `<li class="risk-item${r.rule_id ? '' : ' suggested'}">
<div class="item-head">
<span class="item-label">${escapeHtml(RISK_TYPE[r.type] ?? '其他提示')}</span>
${badge(lookup(SEVERITY, r.severity, '提示'))}
${verification ? badge(verification) : ''}
</div>
<div class="risk-title">${escapeHtml(r.title)}</div>
<p class="risk-detail">${escapeHtml(r.detail)}</p>
${applicabilityNote(ctx.applicability)}
${sourceIds.length ? `<p class="item-note">关联来源：${escapeHtml(sourceIds.map((id) => sourceLabel(id, sourceNames)).join('、'))}</p>` : ''}
${foot.length ? `<div class="risk-foot">${foot.map(escapeHtml).join(' · ')}</div>` : ''}
</li>`
}

function risksSection(content) {
  const risks = content.risks ?? []
  if (!risks.length) return ''
  const itemNames = new Map((content.items ?? []).map((it) => [it.item_id, it.label]))
  // 来源 id → 机构名，取自同一份报告的 provenance，不另建映射表
  const sourceNames = new Map(
    (content.provenance?.sources ?? []).map((s) => [s.source_id, s.authority ?? s.source_id])
  )
  const ruled = risks.filter((r) => r.rule_id)
  const suggested = risks.filter((r) => !r.rule_id)

  const cards = []
  if (ruled.length) {
    cards.push(card('依据规则的提示', `<ul class="item-list">
${ruled.map((r) => riskItem(r, itemNames, sourceNames)).join('\n')}
</ul>`, {
      num: ruled.length,
      sub: '规则适用条件未经人工核实时，提示不代表合规结论。',
    }))
  }
  if (suggested.length) {
    cards.push(card('未经规则校验的提示', `<ul class="item-list">
${suggested.map((r) => riskItem(r, itemNames, sourceNames)).join('\n')}
</ul>`, {
      num: suggested.length,
      sub: '以下提示没有对应的规则编号，属于模型建议，未经过规则校验。',
    }))
  }
  return cards.join('\n')
}

/**
 * 多品名行组：对齐状态与成员行号。
 *
 * 行号是**该文件内的原始行号**，不跨文件通用；报告里带上它是为了让人能回到
 * 原件核对，不是"同一行"的断言。`PARTIAL` / `UNALIGNED` 必须显示出来——
 * 行没对齐意味着比对覆盖不完整。
 */
function itemsSection(content) {
  const items = content.items ?? []
  if (!items.length) return ''
  const fileName = new Map((content.documents ?? []).map((d) => [d.file_id, d.file_name]))

  const rows = items.map((it) => {
    const members = (it.members ?? []).map(
      (m) => `${escapeHtml(fileName.get(m.file_id) ?? m.file_id)} 第 ${escapeHtml(m.item_no)} 行`
    )
    const basis = it.alignment_basis ? ALIGNMENT_BASIS[it.alignment_basis] : null
    return `<tr>
<td><span class="doc-name">${escapeHtml(it.label)}</span>
<div class="doc-meta">${members.join(' · ')}</div></td>
<td class="col-narrow">${badge(lookup(ALIGNMENT_STATUS, it.alignment_status))}</td>
<td>${basis ? escapeHtml(basis) : '<span class="muted">—</span>'}${it.alignment_note ? `<div class="doc-meta">${escapeHtml(it.alignment_note)}</div>` : ''}</td>
</tr>`
  }).join('\n')

  return card('多品名行组', `<table class="table">
<thead><tr><th>商品</th><th>对齐状态</th><th>对齐依据与说明</th></tr></thead>
<tbody>
${rows}
</tbody>
</table>`, { sub: '行号是各文件内的原始行号，仅用于回到原件核对。' })
}

/**
 * 未归组商品行。
 *
 * 这些行没能和别的文件对上，**只作为单文件证据**，不能当作整票结论的依据。
 * 后端专门保留了它们，就是为了不让证据在归组失败时静默消失。
 */
function unalignedSection(content) {
  const rows = content.unaligned_evidence ?? []
  if (!rows.length) return ''
  const fileName = new Map((content.documents ?? []).map((d) => [d.file_id, d.file_name]))

  const list = rows.map((row) => {
    const fields = (row.fields ?? []).map(
      (f) => `<li><span class="id-label">${escapeHtml(f.label)}</span><span class="id-value">${fieldValue(f)}</span>${fieldStatusBadge(f.status)}</li>`
    ).join('')
    return `<li class="issue-item sev-muted">
<div class="item-head">
<span class="item-label">${escapeHtml(fileName.get(row.file_id) ?? row.file_id)} 第 ${escapeHtml(row.item_no)} 行</span>
</div>
${row.raw_text ? `<p class="item-note">原文：<span class="mono">${escapeHtml(row.raw_text)}</span></p>` : ''}
<ul class="id-list">${fields}</ul>
</li>`
  }).join('\n')

  return card('未能归组的商品行', `<ul class="item-list">
${list}
</ul>`, {
    num: rows.length,
    sub: '这些行未在其他文件中找到对应行，仅作为该文件的单行证据，不能当作整票结论的依据。',
  })
}

/** 错误与警告。失败页码与受控原因由后端保留，这里原样呈现 */
function errorsSection(content) {
  const errors = content.errors ?? []
  if (!errors.length) return ''

  const list = errors.map((e) => `<li class="err-item">
<span class="err-code">${escapeHtml(e.code)}</span>
<span class="err-msg">${escapeHtml(e.message)}</span>
${badge(lookup(ERROR_LEVEL, e.level))}
</li>`).join('\n')

  return card('错误与警告', `<ul class="item-list">
${list}
</ul>`, { num: errors.length })
}

/**
 * 人工修正审计。
 *
 * 只呈现有效值/单位/状态的前后变化与修正原因——完整的字段级原始证据在
 * 归档视图里，不进默认报告正文（#51 第 1 点）。操作者身份未认证是事实，
 * 如实写出来，不暗示已经确认过是谁改的。
 */
function correctionsSection(content) {
  const corrections = content.corrections ?? []
  if (!corrections.length) return ''

  const list = corrections.map((c) => {
    const changes = (c.changes ?? []).map((ch) => {
      const before = ch.before ?? {}
      const after = ch.after ?? {}
      const b = formatValue(before.normalized_value, typeof before.normalized_value === 'number' ? 'NUMBER' : 'STRING', before.unit)
      const a = formatValue(after.normalized_value, typeof after.normalized_value === 'number' ? 'NUMBER' : 'STRING', after.unit)
      return `<div class="change-row">
<span class="mono">${escapeHtml(ch.field_key)}</span>
<span class="value-main">${escapeHtml(b.main)}${before.unit ? ` ${escapeHtml(before.unit)}` : ''}</span>
<span class="change-arrow">→</span>
<span class="value-main">${escapeHtml(a.main)}${after.unit ? ` ${escapeHtml(after.unit)}` : ''}</span>
</div>`
    }).join('\n')

    return `<li class="corr-item">
<div class="item-head">
<span class="item-label">修正于 ${escapeHtml(formatTime(c.created_at))}</span>
<span class="item-scope">操作者身份未认证</span>
</div>
<p class="corr-reason">修正原因：${escapeHtml(c.reason)}</p>
${changes}
<div class="item-foot">源任务 ${escapeHtml(c.source_task_id)} · 派生任务 ${escapeHtml(c.derived_task_id)}</div>
</li>`
  }).join('\n')

  return card('人工修正记录', `<ul class="item-list">
${list}
</ul>`, { sub: '原始证据与原始读数保持不变；以下为有效值的前后变化。' })
}

/**
 * 版本与来源。
 *
 * 关键一条：`execution_rule_version` 为 null 时写"未记录"，**不用当前版本回填**。
 * 后端同时给了当前导出时的定义版本，两者是不同时点的东西，必须分开陈述——
 * 混在一层里会让人以为当时就是按这个版本跑的。
 */
function provenanceSection(content) {
  const p = content.provenance ?? {}
  const limitations = content.limitations ?? []

  const rows = [
    ['执行时规则版本', p.execution_rule_version ?? '未记录（原任务没有留下历史版本）'],
    ['版本记录状态', EXECUTION_VERSION_STATUS[p.execution_version_status] ?? plain(p.execution_version_status)],
    ['规则核实状态', p.rule_verification_status ? lookup(VERIFICATION_STATUS, p.rule_verification_status).text : '未知'],
    ['当前规则定义版本', p.current_definition_version ?? '未知'],
    ['来源元数据范围', p.source_metadata_scope === 'CURRENT_AT_EXPORT' ? '导出时的当前信息（不代表任务执行时的状态）' : plain(p.source_metadata_scope)],
    ['来源监测模式', p.monitor_mode === 'runtime_monitor' ? '运行时监测' : p.monitor_mode === 'bundled_static' ? '内置静态目录（未配置监测）' : plain(p.monitor_mode)],
    ['来源检查时间', p.monitor_checked_at ? formatTime(p.monitor_checked_at) : '未检查'],
  ]

  /**
   * 来源列表。
   *
   * `status` 与 `review_status` 都是后端枚举（`NOT_CHECKED` /
   * `APPLICABILITY_REVIEW_REQUIRED`），必须译成中文再展示——这是 issue #51
   * 第 3 点明确点名的问题：内部标识被当成展示文案。
   *
   * 展示用 `authority`（机构名，如 European Commission / EUR-Lex）而不是
   * `source_id`：后者是内部关联键，对读者没有意义。`source_id` 只在
   * 风险条目里作为"关联来源"出现时保留，用于和规则定义对照。
   * `url` 在导出件里保留成可点的链接——来源的可追溯性靠它。
   */
  const sourceItems = (p.sources ?? []).map((s) => {
    const status = s.status ? lookup(SOURCE_STATUS, s.status) : null
    const review = s.review_status ? lookup(SOURCE_REVIEW_STATUS, s.review_status) : null
    const name = s.authority ?? s.source_id ?? '来源'
    const label = s.url
      ? `<a href="${escapeHtml(s.url)}" rel="noreferrer noopener">${escapeHtml(name)}</a>`
      : escapeHtml(name)
    const tags = [status?.text, review?.text].filter(Boolean)
    return `<li><span class="plain-value">${label}${tags.length ? ` · ${escapeHtml(tags.join(' · '))}` : ''}</span></li>`
  }).join('')

  const pending = (p.pending_updates ?? []).map((u) => {
    const status = u.status ? lookup(SOURCE_STATUS, u.status) : null
    return `<li><span class="plain-value">${escapeHtml(u.source_id ?? '来源')} · ${escapeHtml(status?.text ?? '待复核')}</span></li>`
  }).join('')

  const sourceBlock = sourceItems || pending
    ? `<p class="card-sub" style="margin-top:var(--space-4)">本票关联来源</p><ul class="plain-list">${sourceItems}${pending}</ul>
<p class="foot-note">来源成功抓取或目录中列出，不等于法律适用已经核实。</p>`
    : '<p class="foot-note">本票未关联到具体来源记录。</p>'

  return card('版本与来源记录', `
<ul class="plain-list">
${rows.map(([k, v]) => `<li><span class="plain-key">${escapeHtml(k)}</span><span class="plain-value">${escapeHtml(plain(v))}</span></li>`).join('\n')}
</ul>
${sourceBlock}
${limitations.length ? `<p class="card-sub" style="margin-top:var(--space-4)">本报告的使用限制</p><ul class="plain-list">
${limitations.map((l) => `<li><span class="plain-value">${escapeHtml(LIMITATION_TEXT[l] ?? l)}</span></li>`).join('\n')}
</ul>` : ''}
<p class="foot-note">结果指纹 <span class="mono">${escapeHtml(content.result_hash)}</span>（原结果标识，不因报告投影改变）</p>
`, { sub: '来源与规则版本用于追溯，不代表法律适用已经核实。' })
}

/* --------------------------------------------------------------------------
   入口
   -------------------------------------------------------------------------- */

/**
 * 生成导出用的完整 HTML 文档。
 *
 * @param {object} content 报告契约 v2 的 `view=content` 响应体
 * @returns {string} 自包含的 HTML 文档
 */
export function buildReportHtml(content) {
  if (!content || typeof content !== 'object') {
    throw new TypeError('buildReportHtml 需要报告内容对象')
  }
  const task = content.task ?? {}
  const failedDocs = (content.documents ?? []).filter(
    (d) => d.process_status === 'FAILED' || d.process_status === 'UNSUPPORTED'
  )

  const notices = []
  if (task.status === 'FAILED') {
    notices.push(notice('bad', '本次检查失败', '未产生比对结果，本报告仅保留失败明细与文件处理情况，可用于留档。'))
  } else if (task.status === 'PARTIAL') {
    notices.push(notice('warn', '本报告基于不完整的结果', `${failedDocs.length} 份文件未能处理成功，其数据未参与比对。`))
  }
  if (content.errors?.some((e) => e.code === 'HUMAN_CORRECTED')) {
    notices.push(notice('info', '本报告包含人工修正', '有效抽取值经人工修正并重算，原始证据保留，操作者身份未认证。'))
  }
  notices.push(notice('info', '处理完成不代表合规通过', '单一来源、未校验、无法比对与未核实的规则必须分别核对；本报告不是合规结论，也不替代法律适用核实。'))

  const body = `<main class="report">
${header(content)}
${notices.join('\n')}
${documentsSection(content)}
${issuesSection(content)}
${remainingSection(content)}
${risksSection(content)}
${itemsSection(content)}
${unalignedSection(content)}
${errorsSection(content)}
${correctionsSection(content)}
${provenanceSection(content)}
<footer class="report-foot">
单证检查报告 · 任务 ${escapeHtml(plain(task.task_id))} · 生成于 ${escapeHtml(formatTime(content.generated_at))}<br>
本文件由前端依据后端结构化报告内容生成，可离线保存或打印为 PDF。
</footer>
</main>`

  return page({ title: `单证检查报告 · ${plain(task.task_id)}`, body })
}

/**
 * 建议的下载文件名。任务编号里可能有文件系统不友好的字符，统一收敛成下划线，
 * 与后端 `Content-Disposition` 的处理方式一致。
 *
 * @returns {string} 如 `report-tsk_20261012_0001.html`
 */
export function reportFileName(content, extension = 'html') {
  const safe = String(content?.task?.task_id ?? 'report').replace(/[^A-Za-z0-9_-]/g, '_')
  return `report-${safe}.${extension}`
}
