/** 「需关注」口径：MATCH 比对含 LOW_CONFIDENCE 取值时也必须算待复核 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { needsReview, PROBLEM_STATUSES } from '../web/src/utils/needsReview.js'

const mk = (status, fieldStatuses = []) => ({
  status,
  values: fieldStatuses.map((fs) => ({ field_status: fs })),
})

test('问题状态集合内的状态一律需关注', () => {
  for (const status of PROBLEM_STATUSES) {
    assert.equal(needsReview(mk(status)), true, status)
  }
})

test('MATCH / SINGLE_SOURCE 且取值正常：不需关注', () => {
  assert.equal(needsReview(mk('MATCH', ['EXTRACTED', 'EXTRACTED'])), false)
  assert.equal(needsReview(mk('SINGLE_SOURCE', ['EXTRACTED'])), false)
})

test('MATCH 但任一取值 LOW_CONFIDENCE：需关注（只在「全部」里可见是不够的）', () => {
  assert.equal(needsReview(mk('MATCH', ['EXTRACTED', 'LOW_CONFIDENCE'])), true)
})

test('values 缺失时不抛错、不误判', () => {
  assert.equal(needsReview({ status: 'MATCH' }), false)
  assert.equal(needsReview({ status: 'CONFLICT' }), true)
})
