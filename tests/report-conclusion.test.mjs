/** 报告页结论推导：不允许把未校验/单来源概括成"全部一致"；tone 与文案同源 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildConclusion } from '../web/src/utils/reportConclusion.js'

const base = {
  status: 'COMPLETED',
  documentCount: 3,
  fieldCount: 15,
  riskCount: 0,
  failedDocCount: 0,
}
const mkCounts = (over = {}) => ({
  total: 0, match: 0, single: 0, unchecked: 0, conflict: 0, missing: 0, unrecognized: 0,
  ...over,
})

test('非终态（PROCESSING/PENDING/FAILED）不下结论', () => {
  for (const status of ['PROCESSING', 'PENDING', 'FAILED']) {
    assert.equal(buildConclusion({ ...base, status, counts: mkCounts({ total: 4, match: 4 }) }), null)
  }
})

test('clean 样例（4 MATCH + 4 SINGLE_SOURCE）：不再宣称 15 个字段全部一致', () => {
  const { text, tone } = buildConclusion({ ...base, counts: mkCounts({ total: 8, match: 4, single: 4 }) })
  assert.ok(text.includes('4 个比对条目全部一致'))
  assert.ok(text.includes('无法交叉比对'))
  assert.ok(!text.includes('15 个字段全部一致'))
  // 有无法交叉比对的字段，不算"全部一致"，不是绿色
  assert.equal(tone, 'neutral')
})

test('含 NOT_CHECKED：明确表示尚有未校验项，不能判定全部一致', () => {
  const { text, tone } = buildConclusion({ ...base, counts: mkCounts({ total: 5, match: 4, unchecked: 1 }) })
  assert.ok(text.includes('1 项未校验'))
  assert.ok(text.includes('不能判定为全部一致'))
  assert.equal(tone, 'warn')
})

test('纯 SINGLE_SOURCE：说明无法交叉比对，不称一致', () => {
  const { text, tone } = buildConclusion({ ...base, counts: mkCounts({ total: 3, single: 3 }) })
  assert.ok(text.includes('无法交叉比对'))
  assert.ok(!text.includes('一致，'))
  assert.equal(tone, 'neutral')
})

test('comparisons 为空：不产生一致结论', () => {
  const { text, tone } = buildConclusion({ ...base, counts: mkCounts() })
  assert.ok(text.includes('未产生任何比对条目'))
  assert.ok(!text.includes('全部一致'))
  assert.equal(tone, 'neutral')
})

test('纯 MATCH 的完成任务：仍能给出范围准确的正向结论，绿色', () => {
  const { text, tone } = buildConclusion({ ...base, counts: mkCounts({ total: 6, match: 6 }) })
  assert.ok(text.includes('3 份文件、6 个比对条目全部一致'))
  assert.ok(text.includes('未发现风险提示'))
  assert.equal(tone, 'ok')
})

test('有问题条目：需要人工复核，未校验项一并念出，红色', () => {
  const { text, tone } = buildConclusion({
    ...base,
    counts: mkCounts({ total: 8, match: 4, conflict: 2, missing: 1, unchecked: 1 }),
  })
  assert.ok(text.includes('2 处不一致'))
  assert.ok(text.includes('1 处部分缺失'))
  assert.ok(text.includes('1 项尚未校验'))
  assert.ok(text.includes('需要人工复核'))
  assert.equal(tone, 'bad')
})

test('PARTIAL：必须带不完整前缀；即使全一致也只是橙色', () => {
  const { text, tone } = buildConclusion({
    ...base,
    status: 'PARTIAL',
    failedDocCount: 1,
    counts: mkCounts({ total: 4, match: 4 }),
  })
  assert.ok(text.startsWith('1 份文件未能处理，本报告基于不完整结果。'))
  assert.equal(tone, 'warn')
})

test('PARTIAL 且有问题条目：红色优先', () => {
  const { tone } = buildConclusion({
    ...base,
    status: 'PARTIAL',
    failedDocCount: 1,
    counts: mkCounts({ total: 4, match: 3, conflict: 1 }),
  })
  assert.equal(tone, 'bad')
})

test('counts 缺失：不下结论', () => {
  assert.equal(buildConclusion({ ...base, counts: null }), null)
})
