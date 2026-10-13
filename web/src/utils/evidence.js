/**
 * 抽取层原文证据索引（纯函数，便于单测）。
 *
 * 比对条目（comparison.values）里的 raw_value 读不出值时为 null，
 * 但抽取层（extractions[].fields）可能仍保留着原文片段 raw_text。
 * 这里以 file_id + item_id + field_key 关联两者——绝不只按 field_key
 * 关联，否则多商品任务的同名字段会互相串证据。
 */

/**
 * @param {Array} extractions task.extractions
 * @returns {Map<string, Array>} `${file_id} ${field_key}` → 该文件内同名字段数组
 */
export function buildEvidenceIndex(extractions) {
  const index = new Map()
  for (const ext of extractions ?? []) {
    for (const f of ext?.fields ?? []) {
      const key = `${ext.file_id} ${f.field_key}`
      if (!index.has(key)) index.set(key, [])
      index.get(key).push(f)
    }
  }
  return index
}

/**
 * 查某个比对值对应的抽取层原文片段。
 *
 * 归属匹配规则：
 * - 优先精确匹配 item_id（value.item_id 缺省时用 comparison.item_id）；
 * - 查整票字段（itemId 为 null）时，候选里带 line_no 的是"未分组商品行"，
 *   不是整票证据，必须从精确匹配与回退中都排除，否则整票比较会串到
 *   某一行商品的原文（M02 回归：line_no=7 的 8 PCS 会盖过整票 100 PCS）；
 * - 后端没给字段标注商品归属、且该行也没有行号（item_id 与 line_no 均缺失/null）、
 *   同名字段只有一条时，归属没有歧义，可以安全回退；
 *   带行号的未分组字段不算安全回退——它属于某一行商品，只是后端没归组；
 * - 同名字段有多条又无法区分归属时不猜，返回 null（不串证据）。
 *
 * @returns {string|null} 原文片段；没有证据或证据为空时为 null（调用方如实显示无证据）
 */
export function evidenceRawText(index, comparison, value) {
  if (!index || !comparison || !value) return null
  const itemId = value.item_id ?? comparison.item_id ?? null
  const candidates = index.get(`${value.file_id} ${comparison.field_key}`) ?? []

  /** 查整票字段时排除带行号的未分组商品行；查商品字段时维持精确 item_id 匹配 */
  const exact =
    itemId === null
      ? candidates.filter((f) => (f.item_id ?? null) === null && (f.line_no ?? null) === null)
      : candidates.filter((f) => (f.item_id ?? null) === itemId)

  const field =
    (exact.length === 1 ? exact[0] : null) ??
    (candidates.length === 1 &&
    (candidates[0].item_id ?? null) === null &&
    (candidates[0].line_no ?? null) === null
      ? candidates[0]
      : null)

  const text = field?.raw_text
  return typeof text === 'string' && text.trim() ? text : null
}
