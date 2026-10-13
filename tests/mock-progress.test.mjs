import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import Ajv from 'ajv/dist/2020.js'
import { mockSnapshot, startMockTask } from '../web/src/api/mockProgress.js'

test('禁用存储时仍能排队、处理并保留失败终态', (t) => {
  let now = 1800000000000
  t.mock.method(Date, 'now', () => now)
  globalThis.window = { sessionStorage: { getItem() { throw new Error('禁用存储') } } }
  t.after(() => { delete globalThis.window })
  const sample = { status: 'PARTIAL', documents: Array.from({ length: 4 }, (_, i) => ({
    file_id: 'f' + i, process_status: i === 1 ? 'FAILED' : 'EXTRACTED', page_count: 1,
    error_message: i === 1 ? '无法解析' : null,
  })), comparisons: [{ status: 'NOT_CHECKED' }], risks: [{ rule_id: null }] }
  const id = startMockTask()
  const queued = mockSnapshot(id, sample)
  assert.equal(queued.status, 'PENDING')
  assert.ok(queued.documents.every((d) => d.process_status === 'UPLOADED' && d.error_message === null))
  assert.deepEqual(queued.comparisons, [])
  now += 1800
  assert.equal(mockSnapshot(id, sample).documents[0].process_status, 'PARSING')
  now += 5800
  const comparing = mockSnapshot(id, sample)
  assert.equal(comparing.status, 'PROCESSING')
  assert.deepEqual(comparing.documents.map((d) => d.process_status), ['EXTRACTED', 'FAILED', 'EXTRACTED', 'EXTRACTED'])
  now += 1500
  const done = mockSnapshot(id, sample)
  assert.equal(done.status, 'PARTIAL')
  assert.deepEqual(done.comparisons, sample.comparisons)
  assert.deepEqual(done.risks, sample.risks)
  assert.equal(new Date(done.finished_at) - new Date(done.created_at), 9000)
  assert.equal(sample.documents[1].process_status, 'FAILED')
})

test('所有终态样例的各阶段符合契约，业务结果不变', (t) => {
  let now = 1800000100000
  t.mock.method(Date, 'now', () => now)
  const schema = JSON.parse(readFileSync(new URL('../docs/schema/check-task.schema.json', import.meta.url)))
  const validate = new Ajv({ strict: false, validateFormats: false }).compile(schema)
  const folder = new URL('../web/src/mock/', import.meta.url)
  for (const name of readdirSync(folder).filter((name) => name.startsWith('check-'))) {
    const { _comment, ...sample } = JSON.parse(readFileSync(new URL(name, folder)))
    if (!['COMPLETED', 'PARTIAL', 'FAILED'].includes(sample.status)) continue
    const original = structuredClone(sample)
    const start = now
    const id = startMockTask()
    for (const elapsed of [0, 1500, 4500, 8000, 10000]) {
      now = start + elapsed
      const snapshot = mockSnapshot(id, sample)
      assert.ok(validate(snapshot), name + ': ' + JSON.stringify(validate.errors))
      if (elapsed === 10000) {
        const { task_id, created_at, finished_at, ...business } = snapshot
        const { task_id: oldId, created_at: oldStart, finished_at: oldEnd, ...expected } = sample
        assert.deepEqual(business, expected, name)
      }
    }
    assert.deepEqual(sample, original)
  }
})
