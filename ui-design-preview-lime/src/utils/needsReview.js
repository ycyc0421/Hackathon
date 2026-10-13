/**
 * 「需关注」判定：一条比对是否需要人工复核。
 *
 * 口径：比对状态属于问题状态集合，或任一取值的 field_status 为
 * LOW_CONFIDENCE（徽章「请核对」）。注意 MATCH 比对也可能含
 * LOW_CONFIDENCE 取值——只看状态集合会漏掉它们，用户处理完默认
 * 「需关注」列表 ≠ 处理完全部复核要求。
 *
 * 差异页筛选与计数、报告页问题条目、顶栏差异页角标三处共用本函数，
 * 口径必须保持一致，不允许各页面自己再写一份等价判断。
 */

/** 需要人工看一眼的比对状态，包括未校验（未校验 ≠ 没有问题） */
export const PROBLEM_STATUSES = ['CONFLICT', 'MISSING_IN_SOME', 'NOT_CHECKED', 'UNRECOGNIZED']

export function needsReview(comparison) {
  if (PROBLEM_STATUSES.includes(comparison.status)) return true
  return (comparison.values ?? []).some((v) => v.field_status === 'LOW_CONFIDENCE')
}
