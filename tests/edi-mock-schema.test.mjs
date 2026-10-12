/**
 * web/src/mock 下的 EDI 合成夹具回归（issue #40）。
 *
 * 根目录 npm run validate 只扫 docs/fixtures，不会扫前端 mock 副本；
 * 这里按同一 CheckTask schema 与 summary 自洽性校验前端注册的六个 EDI 场景，
 * 保证示例数据始终符合契约、且夹具间的关联/证据一致。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import Ajv2020 from 'ajv/dist/2020.js'
import { buildEvidenceIndex, evidenceRawText } from '../web/src/utils/evidence.js'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function load(rel) {
  return JSON.parse(readFileSync(join(root, rel), 'utf8'))
}

/** 与 docs/schema/validate.mjs 相同的处理：去掉说明性键，按 CheckTask 校验 */
function stripComments(value) {
  if (Array.isArray(value)) return value.map(stripComments)
  if (value && typeof value === 'object') {
    const out = {}
    for (const [k, v] of Object.entries(value)) {
      if (k === '_comment') continue
      out[k] = stripComments(v)
    }
    return out
  }
  return value
}

const ajv = new Ajv2020({ allErrors: true, strict: false })
const validateTask = ajv.compile(load('docs/schema/check-task.schema.json'))

const ediMocks = readdirSync(join(root, 'web/src/mock'))
  .filter((f) => f.startsWith('check-edi-') && f.endsWith('.json'))
  .sort()

test('注册了全部六个 EDI 场景夹具', () => {
  assert.deepEqual(
    ediMocks,
    [
      'check-edi-failed.json',
      'check-edi-mixed.json',
      'check-edi-multi-item.json',
      'check-edi-only.json',
      'check-edi-partial.json',
      'check-edi-unsupported.json',
    ]
  )
})

for (const name of ediMocks) {
  test(`${name} 符合 CheckTask schema 且 summary 自洽`, () => {
    const data = stripComments(load(`web/src/mock/${name}`))
    const ok = validateTask(data)
    if (!ok) {
      assert.fail(
        validateTask.errors.map((e) => `${e.instancePath || '/'} ${e.message}`).join('\n')
      )
    }
    // summary 计数与数组长度一致（与根 validate 同一口径）
    const expect = {
      document_count: data.documents?.length,
      field_count: (data.extractions ?? []).reduce((n, e) => n + (e.fields?.length ?? 0), 0),
      conflict_count: data.comparisons.filter((c) => c.status === 'CONFLICT').length,
      missing_count: data.comparisons.filter((c) => c.status === 'MISSING_IN_SOME').length,
      risk_count: data.risks?.length,
      unrecognized_count: data.comparisons.filter((c) => c.status === 'UNRECOGNIZED').length,
    }
    for (const [k, v] of Object.entries(expect)) {
      assert.equal(data.summary[k], v, `summary.${k}`)
    }
    // EDI 原件保留合成标识，不冒充真实接口输出
    assert.match(data.input?.notes ?? '', /合成|非真实接口输出/)
  })
}

// —— 关键关联与展示约束（不只校验形状） ——

test('check-edi-mixed：EDI 无页码，PDF/图片为第 1 页，不串页码', () => {
  const d = load('web/src/mock/check-edi-mixed.json')
  const byFile = Object.fromEntries(d.documents.map((x) => [x.file_id, x]))
  assert.equal(byFile.f_edi.page_count, null)
  assert.equal(byFile.f_pdf.page_count, 1)
  assert.equal(byFile.f_image.page_count, 1)
  const cmp = d.comparisons.find((c) => c.field_key === 'quantity')
  const pages = Object.fromEntries(cmp.values.map((v) => [v.file_id, v.page]))
  assert.equal(pages.f_edi, null)
  assert.equal(pages.f_pdf, 1)
  assert.equal(pages.f_image, 1)
})

test('check-edi-multi-item：票级 120 与行级 100/20 分层，乱序不串商品', () => {
  const d = load('web/src/mock/check-edi-multi-item.json')
  const pkgs = d.comparisons.filter((c) => c.field_key === 'packages')
  // 票级与两个商品行各自成组（item_id 区分），不重复相加
  const shipment = pkgs.find((c) => c.item_id === null)
  const lines = Object.fromEntries(
    pkgs.filter((c) => c.item_id !== null).map((c) => [c.item_id, c.values.map((v) => v.normalized_value)])
  )
  assert.deepEqual(shipment.values.map((v) => v.normalized_value), [120, 120])
  assert.deepEqual(lines.item_mug, [100, 100])
  assert.deepEqual(lines.item_glass, [20, 20])
})

test('check-edi-multi-item：GLS300 数量缺失，按 file_id+item_id+field_key 各归各位', () => {
  const d = load('web/src/mock/check-edi-multi-item.json')
  const glassQty = d.comparisons.find((c) => c.field_key === 'quantity' && c.item_id === 'item_glass')
  assert.equal(glassQty.status, 'MISSING_IN_SOME')
  const missing = glassQty.values.find((v) => v.field_status === 'MISSING_IN_DOC')
  assert.ok(missing, 'GLS300 数量在第二份中应为 MISSING_IN_DOC')
  // 缺失不因另一商品（MUG350 有值）被掩盖
  const mugQty = d.comparisons.find((c) => c.field_key === 'quantity' && c.item_id === 'item_mug')
  assert.equal(mugQty.status, 'MATCH')
})

test('check-edi-only：0 冲突不等于通过——SINGLE_SOURCE 与 NOT_CHECKED 保留', () => {
  const d = load('web/src/mock/check-edi-only.json')
  assert.equal(d.status, 'COMPLETED')
  assert.equal(d.summary.conflict_count, 0)
  const statuses = d.comparisons.map((c) => c.status)
  assert.ok(statuses.includes('SINGLE_SOURCE'))
  assert.ok(statuses.includes('NOT_CHECKED'))
})

test('check-edi-partial：失败文件保留错误与原件，有效文件仍有结果', () => {
  const d = load('web/src/mock/check-edi-partial.json')
  assert.equal(d.status, 'PARTIAL')
  const failed = d.documents.find((x) => x.process_status === 'FAILED')
  assert.ok(failed?.error_message)
  assert.equal(failed.file_name, 'invoice-truncated.edi')
  assert.ok(d.errors.some((e) => e.code === 'DOC_PARSE_FAILED'))
  assert.ok(d.comparisons.length > 0, '有效文件仍应产出比较')
})

test('check-edi-unsupported / check-edi-failed：空比较不显示「通过」，错误如实保留', () => {
  for (const name of ['check-edi-unsupported.json', 'check-edi-failed.json']) {
    const d = load(`web/src/mock/${name}`)
    assert.equal(d.status, 'FAILED')
    assert.equal(d.comparisons.length, 0)
    assert.ok(d.errors.some((e) => e.level === 'FATAL'))
  }
})

test('check-edi-multi-item：字段证据按 file_id+item_id+field_key 关联，不串商品', () => {
  const d = load('web/src/mock/check-edi-multi-item.json')
  const index = buildEvidenceIndex(d.extractions)
  // 两个商品都有 quantity 原文：必须各归各位；缺失的那份如实返回 null
  const mug = evidenceRawText(index, { field_key: 'quantity', item_id: 'item_mug' }, { file_id: 'f_multi' })
  const glass = evidenceRawText(index, { field_key: 'quantity', item_id: 'item_glass' }, { file_id: 'f_multi' })
  assert.ok(mug?.includes('2400'))
  assert.ok(glass?.includes('800'))
  const glassMissing = evidenceRawText(index, { field_key: 'quantity', item_id: 'item_glass' }, { file_id: 'f_missing' })
  assert.equal(glassMissing, null, 'GLS300 数量缺失的第二份不能返回原文证据')
})
