/**
 * 比对结果里「哪份文件与其他不同」的派生判定。
 *
 * 以多数派为基准：某取值的出现次数严格最多时，只有取不同值的文件
 * 标为 divergent（如 2400/2500/2500 只标 2400 那份）。
 * 没有多数派时（取值全不同，或最多次数并列）没有基准可言，
 * 所有有值的文件都标出——含义是「无法确定以谁为准」，
 * 由各展示位自行决定是否附说明，不要渲染成「全都错了」。
 *
 * 只对 CONFLICT 做判定：其余状态（未校验、单来源等）没有
 * 「与谁不同」的语义，一律返回空集合。
 */
export function divergenceInfo(comparison) {
  const empty = { divergent: new Set(), hasMajority: false, valuedCount: 0 }
  if (comparison?.status !== 'CONFLICT') return empty

  const valued = (comparison.values ?? []).filter(
    (v) => v.normalized_value !== null && v.normalized_value !== undefined
  )
  if (valued.length < 2) return empty

  const counts = new Map()
  for (const v of valued) {
    const key = String(v.normalized_value)
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  if (counts.size < 2) return empty

  let topKey = null
  let topCount = 0
  let tie = false
  for (const [key, n] of counts) {
    if (n > topCount) {
      topKey = key
      topCount = n
      tie = false
    } else if (n === topCount) {
      tie = true
    }
  }
  const hasMajority = !tie && topCount > 1

  const divergent = new Set()
  for (const v of valued) {
    if (!hasMajority || String(v.normalized_value) !== topKey) divergent.add(v.file_id)
  }
  return { divergent, hasMajority, valuedCount: valued.length }
}

/** 只要 divergent 文件 id 集合时的便捷入口 */
export function divergentFileIds(comparison) {
  return divergenceInfo(comparison).divergent
}
