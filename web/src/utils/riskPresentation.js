/**
 * 风险提示展示归一化（在屏 ReportPage 与导出报告 document.js 共用）。
 *
 * 背景：
 * 1. 后端 CheckTask（GET /api/v1/checks/{id}）在 `rules.py` 中为了防免责遗漏，
 *    将 `【演示规则·未经核实】`、`（说明：本提示来自团队自拟的演示规则……）`、
 *    `（官方来源候选；适用条件未经人工核实）` 硬拼进了每条风险的 title / detail / rule_source，
 *    并把商品名 `（品名：xxx）` 拼在标题末尾。
 * 2. 导出报告契约 v2（`report_content.py`）在服务端剥离了上述未核实前后缀并转为
 *    `rule_context.verification_status = 'UNVERIFIED'`，但保留了标题末尾的 `（品名：xxx）`
 *    以及 `rule_source` 中以分号拼接的裸 URL。
 * 3. 本模块在前端展示层把两条路径统一收口：
 *    - 剥离重复堆叠的免责前后缀，转为结构化的 `unverified` 状态（对应 `VERIFICATION_STATUS.UNVERIFIED`）；
 *    - 拆分标题末尾的 `（品名：xxx）` 为独立的 `itemScope`，与「需要处理的条目」胶囊标签一致；
 *    - 将 `rule_source` 中的 HTTP(S) 裸链接解析为可点击的官方来源外链（展示精简域名，悬浮可见完整地址）。
 */

const UNVERIFIED_TITLE_PREFIX = '【演示规则·未经核实】'
const UNVERIFIED_DETAIL_DISCLAIMERS = [
  '（说明：本提示来自团队自拟的演示规则，来源与适用条件尚未核实，不得作为合规依据。）',
  '(说明：本提示来自团队自拟的演示规则，来源与适用条件尚未核实，不得作为合规依据。)',
]
const UNVERIFIED_SOURCE_SUFFIXES = [
  '（团队自拟的演示规则，来源与适用条件未经核实）',
  '(团队自拟的演示规则，来源与适用条件未经核实)',
  '（官方来源候选；适用条件未经人工核实）',
  '(官方来源候选；适用条件未经人工核实)',
]

/**
 * 匹配标题末尾形如 `（品名：陶瓷 马克杯 350ML 白）` 或 `(品名: ...)` 的商品归属后缀。
 * 注意：商品名自身可能含括号（如 `（品名：陶瓷杯 (350ML)）`），因此用贪婪匹配取最后一个 `（品名：` 到行尾闭合括号。
 */
const ITEM_SCOPE_SUFFIX_RE = /^(.*?\S)\s*[（(]品名[：:]\s*(.+?)\s*[）)]\s*$/

/** 匹配后端内部规则集版本号（如 `static-source-candidates-v4`），转为可读中文说明 */
const INTERNAL_RULESET_VERSION_RE = /^static-source-candidates-(v\d+(?:\.\d+)*)$/i

/**
 * 解析单段来源文本。
 * - 若为合法的 http/https URL，返回 `{ text: 域名, href: 完整地址 }`；
 * - 若为普通文本（如“内置目的国规则集 v1”），返回 `{ text, href: null }`。
 *
 * @param {string} rawToken
 * @returns {{ text: string, href: string | null } | null}
 */
export function parseRuleSourceToken(rawToken) {
  const token = String(rawToken ?? '').trim()
  if (!token) return null

  if (/^https?:\/\//i.test(token)) {
    try {
      const parsed = new URL(token)
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        const host = parsed.hostname.replace(/^www\./i, '')
        return {
          text: host || token,
          href: parsed.href,
        }
      }
    } catch {
      // URL 解析失败时安全退回纯文本，不丢来源信息
    }
  }

  const versionMatch = token.match(INTERNAL_RULESET_VERSION_RE)
  if (versionMatch) {
    return {
      text: `内置候选规则集（${versionMatch[1]}）`,
      href: null,
    }
  }

  // 兼容旧版示例或历史任务里的内部措辞
  if (token.startsWith('团队配置的目的国规则集')) {
    return {
      text: token.replace(/^团队配置的/, '内置'),
      href: null,
    }
  }

  return { text: token, href: null }
}

/**
 * 将 `rule_source` 字符串拆分为结构化来源条目列表。
 *
 * 注意：使用负向前瞻 `(?![^&;]{1,10};)` 避免误切分 URL 查询参数中偶发的 HTML 实体（如 `&amp;`），
 * 仅按全角分号 `；` 或两侧非 HTML 实体的半角分号切分多来源列表。
 *
 * @param {string | null | undefined} rawSource
 * @returns {{ sources: Array<{ text: string, href: string | null }>, hadUnverifiedSuffix: boolean }}
 */
export function parseRuleSources(rawSource) {
  let cleaned = String(rawSource ?? '').trim()
  if (!cleaned) return { sources: [], hadUnverifiedSuffix: false }

  let hadUnverifiedSuffix = false
  for (const suffix of UNVERIFIED_SOURCE_SUFFIXES) {
    if (cleaned.includes(suffix)) {
      hadUnverifiedSuffix = true
      cleaned = cleaned.replaceAll(suffix, '').trim()
    }
  }

  const parts = cleaned
    .split(/；|;\s*(?=https?:\/\/|$)/i)
    .map((part) => parseRuleSourceToken(part))
    .filter(Boolean)

  return { sources: parts, hadUnverifiedSuffix }
}

/**
 * 归一化单条风险提示，供页面或导出报告渲染。
 *
 * @param {object} risk 原始风险对象（来自 CheckTask.risks 或 ReportContent.risks）
 * @param {{ taskHasUnverifiedError?: boolean }} [options]
 * @returns {{
 *   title: string,
 *   detail: string,
 *   itemScope: string | null,
 *   unverified: boolean,
 *   sources: Array<{ text: string, href: string | null }>
 * }}
 */
export function presentRisk(risk, { taskHasUnverifiedError = false } = {}) {
  let title = String(risk?.title ?? '').trim()
  let detail = String(risk?.detail ?? '').trim()
  let unverified = Boolean(
    taskHasUnverifiedError || risk?.rule_context?.verification_status === 'UNVERIFIED'
  )

  if (title.includes(UNVERIFIED_TITLE_PREFIX)) {
    unverified = true
    title = title.replaceAll(UNVERIFIED_TITLE_PREFIX, '').trim()
  }

  let itemScope = null
  const scopeMatch = title.match(ITEM_SCOPE_SUFFIX_RE)
  if (scopeMatch) {
    title = scopeMatch[1].trim()
    const extracted = scopeMatch[2].trim()
    if (extracted) itemScope = extracted
  }

  for (const disclaimer of UNVERIFIED_DETAIL_DISCLAIMERS) {
    if (detail.includes(disclaimer)) {
      unverified = true
      detail = detail.replaceAll(disclaimer, '').trim()
    }
  }

  const { sources, hadUnverifiedSuffix } = parseRuleSources(risk?.rule_source)
  if (hadUnverifiedSuffix) {
    unverified = true
  }

  return {
    title,
    detail,
    itemScope,
    unverified,
    sources,
  }
}

/**
 * 过滤任务级 errors[]：当页面已在「依据规则的提示」区块明确展示“未经人工核实”状态时，
 * 不再在底部「错误记录」里把 `RULES_UNVERIFIED` 当成系统错误重复列出（与导出报告 `report_content.py` 一致）。
 *
 * @param {Array<object> | null | undefined} errors
 * @param {{ hasRuledRisks?: boolean }} [options]
 * @returns {Array<object>}
 */
export function visibleTaskErrors(errors, { hasRuledRisks = false } = {}) {
  const list = Array.isArray(errors) ? errors : []
  if (!hasRuledRisks) return list
  return list.filter((e) => e?.code !== 'RULES_UNVERIFIED')
}
