/**
 * 报告页检查概要结论的推导（纯函数，便于单测）。
 *
 * 原则（AGENTS.md 降级原则）：结论只能来自 comparisons 的实际状态，
 * 不能用"零问题计数"反推"全部一致"：
 * - NOT_CHECKED 是没查，不是没问题；含未校验项时不能宣称全部一致；
 * - SINGLE_SOURCE 只有一份文件提供，无法交叉比对，不能称为一致；
 * - comparisons 为空时不下任何正向结论；
 * - 抽取字段数（summary.field_count）是抽取总量，不是比对覆盖范围，
 *   两者分开陈述，不用前者冒充后者。
 *
 * tone 与文案同源推导，供结论条上色（bad 红 / warn 橙 / ok 绿 / neutral 中性），
 * 避免"无论什么情况都是同一种颜色"。
 */

/**
 * @param {object} input
 * @param {string} input.status 任务状态（COMPLETED / PARTIAL 之外一律不下结论）
 * @param {number} input.documentCount 文件份数（summary.document_count）
 * @param {number} input.fieldCount 抽取字段总数（summary.field_count）
 * @param {number} input.riskCount 风险提示数（summary.risk_count）
 * @param {number} [input.failedDocCount] PARTIAL 时未能处理的文件数
 * @param {object} input.counts comparisons 各状态条数：
 *   { total, match, single, unchecked, conflict, missing, unrecognized }
 * @returns {{ text: string, tone: 'bad'|'warn'|'ok'|'neutral' }|null}
 *   不足以得出结论时为 null（页面不渲染该段）
 */
export function buildConclusion({ status, documentCount, fieldCount, riskCount, failedDocCount = 0, counts }) {
  if (status !== 'COMPLETED' && status !== 'PARTIAL') return null
  if (!counts) return null

  const prefix =
    status === 'PARTIAL' ? `${failedDocCount} 份文件未能处理，本报告基于不完整结果。` : ''
  const riskTail = riskCount > 0 ? `，另有 ${riskCount} 条风险提示需要人工查看` : '，未发现风险提示'

  const problems = []
  if (counts.conflict > 0) problems.push(`${counts.conflict} 处不一致`)
  if (counts.missing > 0) problems.push(`${counts.missing} 处部分缺失`)
  if (counts.unrecognized > 0) problems.push(`${counts.unrecognized} 处无法比对`)

  if (problems.length) {
    // 有问题时未校验项也要念出来——它同样需要人工处理
    if (counts.unchecked > 0) problems.push(`${counts.unchecked} 项尚未校验`)
    const riskPart = riskCount > 0 ? `，另有 ${riskCount} 条风险提示` : ''
    return { text: `${prefix}发现 ${problems.join('、')}${riskPart}——需要人工复核。`, tone: 'bad' }
  }

  // 无问题条目：未校验或结果不完整都不能算"通过"，橙色提醒
  const fallbackTone = counts.unchecked > 0 || riskCount > 0 || status === 'PARTIAL' ? 'warn' : 'neutral'

  // 数值一致不能消除抽取可信度问题，概要与人工复核列表使用同一口径。
  if (counts.lowConfidence > 0) {
    const unchecked = counts.unchecked > 0 ? '，另有 ' + counts.unchecked + ' 项未校验' : ''
    return {
      text: prefix + counts.lowConfidence + ' 个比对条目的取值可信度较低' + unchecked + '，需要人工复核' + riskTail + '。',
      tone: 'warn',
    }
  }

  // 以下为"没有问题条目"的分支，逐一区分能不能说"一致"
  if (counts.total === 0) {
    return {
      text: `${prefix}未产生任何比对条目（共 ${documentCount} 份文件、抽取 ${fieldCount} 个字段），无法给出一致性结论${riskTail}。`,
      tone: fallbackTone,
    }
  }

  if (counts.unchecked > 0) {
    const matchPart = counts.match > 0 ? `已比对的 ${counts.match} 个字段一致，` : ''
    const singlePart = counts.single > 0 ? `，另 ${counts.single} 个字段仅一份文件提供` : ''
    return {
      text: `${prefix}${matchPart}尚有 ${counts.unchecked} 项未校验${singlePart}，不能判定为全部一致${riskTail}。`,
      tone: 'warn',
    }
  }

  if (counts.match > 0 && counts.single > 0) {
    return {
      text: `${prefix}${documentCount} 份文件（共抽取 ${fieldCount} 个字段）中，${counts.match} 个比对条目全部一致，另 ${counts.single} 个字段仅一份文件提供、无法交叉比对${riskTail}。`,
      tone: fallbackTone,
    }
  }

  if (counts.match > 0) {
    // 全部比对条目一致且任务完整完成，是唯一可以给出绿色正向结论的形态
    return {
      text: `${prefix}${documentCount} 份文件、${counts.match} 个比对条目全部一致${riskTail}。`,
      tone: status === 'COMPLETED' && riskCount === 0 ? 'ok' : 'warn',
    }
  }

  // 只剩 SINGLE_SOURCE：没有交叉比对的对象，无从谈一致
  return {
    text: `${prefix}共 ${counts.single} 个字段，均仅有一份文件提供，无法交叉比对${riskTail}。`,
    tone: fallbackTone,
  }
}

/**
 * 按 comparisons 的实际状态统计各档条数，供 buildConclusion 与报告导出共用。
 *
 * 单独抽出来是因为报告页与导出的 HTML 报告是同一份结论的两种呈现，
 * 两处各写一份统计迟早会漂移——导出的 PDF 说"3 处不一致"、页面说"2 处"
 * 是最难解释的一类缺陷。
 *
 * 口径：只认 comparisons[].status，不用 summary 里的问题计数反推，
 * 因为 summary 是后端统计的原始任务计数，与比对条目数不是一回事。
 *
 * @param {Array} comparisons task.comparisons
 * @returns {{total:number,match:number,single:number,unchecked:number,conflict:number,missing:number,unrecognized:number}}
 */
export function comparisonCounts(comparisons) {
  const list = comparisons ?? []
  const counts = { total: list.length, match: 0, single: 0, unchecked: 0, conflict: 0, missing: 0, unrecognized: 0, lowConfidence: 0 }
  for (const item of list) {
    if (item?.values?.some((value) => value.field_status === 'LOW_CONFIDENCE')) counts.lowConfidence += 1
    switch (item?.status) {
      case 'MATCH': counts.match += 1; break
      case 'SINGLE_SOURCE': counts.single += 1; break
      case 'NOT_CHECKED': counts.unchecked += 1; break
      case 'CONFLICT': counts.conflict += 1; break
      case 'MISSING_IN_SOME': counts.missing += 1; break
      case 'UNRECOGNIZED': counts.unrecognized += 1; break
      default: break
    }
  }
  return counts
}
