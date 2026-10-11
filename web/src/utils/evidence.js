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
 * - 后端没给字段标注商品归属（item_id 缺失/null）、且该文件内同名字段
 *   只有一条时，归属没有歧义，可以安全使用；
 * - 同名字段有多条又无法区分归属时不猜，返回 null（不串证据）。
 *
 * @returns {string|null} 原文片段；没有证据或证据为空时为 null（调用方如实显示无证据）
 */
export function evidenceRawText(index, comparison, value) {
  if (!index || !comparison || !value) return null
  const itemId = value.item_id ?? comparison.item_id ?? null
  const candidates = index.get(`${value.file_id} ${comparison.field_key}`) ?? []

  const exact = candidates.filter((f) => (f.item_id ?? null) === itemId)
  const field =
    exact[0] ??
    (candidates.length === 1 && (candidates[0].item_id ?? null) === null ? candidates[0] : null)

  const text = field?.raw_text
  return typeof text === 'string' && text.trim() ? text : null
}
