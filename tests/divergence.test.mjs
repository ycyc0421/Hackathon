/** divergence 的多数派判定 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { divergenceInfo } from '../web/src/utils/divergence.js'

const mk = (values, status = 'CONFLICT') => ({
  status,
  values: values.map(([file_id, normalized_value]) => ({ file_id, normalized_value })),
})

test('有多数派：只标少数那份', () => {
  const { divergent, hasMajority } = divergenceInfo(
    mk([['inv.pdf', 2400], ['pl.pdf', 2500], ['bl.pdf', 2500]])
  )
  assert.equal(hasMajority, true)
  assert.deepEqual([...divergent], ['inv.pdf'])
})

test('全不同：没有基准，全部标出', () => {
  const { divergent, hasMajority } = divergenceInfo(
    mk([['a.pdf', 1], ['b.pdf', 2], ['c.pdf', 3]])
  )
  assert.equal(hasMajority, false)
  assert.deepEqual([...divergent].sort(), ['a.pdf', 'b.pdf', 'c.pdf'])
})

test('并列多数（两两相同）也视为无基准，全部标出', () => {
  const { divergent, hasMajority } = divergenceInfo(
    mk([['a.pdf', 1], ['b.pdf', 1], ['c.pdf', 2], ['d.pdf', 2]])
  )
  assert.equal(hasMajority, false)
  assert.deepEqual([...divergent].sort(), ['a.pdf', 'b.pdf', 'c.pdf', 'd.pdf'])
})

test('值带类型差异时按字符串化后的值比较', () => {
  const { divergent } = divergenceInfo(
    mk([['a.pdf', 2400], ['b.pdf', '2400'], ['c.pdf', 2500]])
  )
  assert.deepEqual([...divergent], ['c.pdf'])
})

test('缺值的文件不参与判定、也不被标出', () => {
  const { divergent } = divergenceInfo(
    mk([['a.pdf', 2400], ['b.pdf', 2500], ['c.pdf', 2500], ['d.pdf', null]])
  )
  assert.deepEqual([...divergent], ['a.pdf'])
})

test('非 CONFLICT 状态一律不标', () => {
  for (const status of ['MATCH', 'MISSING_IN_SOME', 'NOT_CHECKED', 'SINGLE_SOURCE']) {
    const { divergent, hasMajority } = divergenceInfo(mk([['a.pdf', 1], ['b.pdf', 2]], status))
    assert.equal(divergent.size, 0)
    assert.equal(hasMajority, false)
  }
})

test('少于两份有值文件时不标', () => {
  const { divergent } = divergenceInfo(mk([['a.pdf', 1], ['b.pdf', null]]))
  assert.equal(divergent.size, 0)
})
