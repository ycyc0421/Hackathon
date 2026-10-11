/** 上传校验：阻塞性限制与同名文件拆分 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { validateFiles, splitByName, UPLOAD_LIMITS } from '../web/src/api/uploadLimits.js'

const mkFile = (name, size = 1024) => ({ name, size })

test('0 份文件：阻塞', () => {
  assert.ok(validateFiles([]).length > 0)
})

test('恰好 10 份、单份不超 20MB：合法', () => {
  const files = Array.from({ length: 10 }, (_, i) => mkFile(`f${i}.pdf`))
  assert.deepEqual(validateFiles(files), [])
})

test('11 份文件：阻塞', () => {
  const files = Array.from({ length: 11 }, (_, i) => mkFile(`f${i}.pdf`))
  assert.ok(validateFiles(files).some((e) => e.includes('一次最多')))
})

test('单份超过 20MB：阻塞并点名文件', () => {
  const big = mkFile('big.png', 21 * 1024 * 1024)
  const errors = validateFiles([big])
  assert.ok(errors.some((e) => e.includes('big.png')))
})

test('移除一个正常文件后复验：剩余超限文件的错误不消失', () => {
  const rest = [mkFile('ok.pdf'), mkFile('big.png', 25 * 1024 * 1024)]
  assert.ok(validateFiles(rest).some((e) => e.includes('big.png')))
})

test('同名不同大小也判为歧义，被拒绝', () => {
  const existing = [mkFile('invoice.pdf', 100)]
  const { fresh, duplicateNames } = splitByName(existing, [mkFile('invoice.pdf', 200)])
  assert.equal(fresh.length, 0)
  assert.deepEqual(duplicateNames, ['invoice.pdf'])
})

test('同一批内重复文件名也被拒绝', () => {
  const { fresh, duplicateNames } = splitByName([], [mkFile('a.pdf'), mkFile('a.pdf'), mkFile('b.pdf')])
  assert.deepEqual(fresh.map((f) => f.name), ['a.pdf', 'b.pdf'])
  assert.deepEqual(duplicateNames, ['a.pdf'])
})

test('不同名文件全部保留', () => {
  const existing = [mkFile('a.pdf')]
  const { fresh, duplicateNames } = splitByName(existing, [mkFile('b.pdf'), mkFile('c.pdf')])
  assert.equal(fresh.length, 2)
  assert.deepEqual(duplicateNames, [])
})

test('上限配置与契约当前处理方式一致（10 份 / 20MB）', () => {
  assert.equal(UPLOAD_LIMITS.maxFiles, 10)
  assert.equal(UPLOAD_LIMITS.maxFileSizeMB, 20)
})
