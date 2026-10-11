/** 抽取层原文证据回退：file_id + item_id + field_key 关联，多商品不串证据 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildEvidenceIndex, evidenceRawText } from '../web/src/utils/evidence.js'

const extractions = [
  {
    file_id: 'f1',
    fields: [
      // 双商品同名字段：必须按 item_id 区分
      { field_key: 'quantity', item_id: 'item_001', raw_text: 'QTY: 2400 PCS', raw_value: '2400 PCS', normalized_value: 2400, status: 'EXTRACTED' },
      { field_key: 'quantity', item_id: 'item_002', raw_text: 'QTY: 500 PCS', raw_value: '500 PCS', normalized_value: 500, status: 'EXTRACTED' },
      // 读不出值但保留了原文片段
      { field_key: 'gross_weight', item_id: 'item_001', raw_text: 'G.W. *********', raw_value: null, normalized_value: null, status: 'UNRECOGNIZED' },
      // 原文片段也缺失
      { field_key: 'volume', item_id: 'item_001', raw_text: null, raw_value: null, normalized_value: null, status: 'UNRECOGNIZED' },
      // 后端未标注商品归属的整票字段
      { field_key: 'invoice_no', raw_text: 'INVOICE NO. INV-1', raw_value: 'INV-1', normalized_value: 'INV-1', status: 'EXTRACTED' },
    ],
  },
]
const index = buildEvidenceIndex(extractions)

test('raw_value 为空但 raw_text 有值：取到原文片段', () => {
  const c = { field_key: 'gross_weight', item_id: 'item_001' }
  const v = { file_id: 'f1', raw_value: null }
  assert.equal(evidenceRawText(index, c, v), 'G.W. *********')
})

test('同文件不同商品的同名字段：分别取到正确证据，不串', () => {
  const c1 = { field_key: 'quantity', item_id: 'item_001' }
  const c2 = { field_key: 'quantity', item_id: 'item_002' }
  assert.equal(evidenceRawText(index, c1, { file_id: 'f1' }), 'QTY: 2400 PCS')
  assert.equal(evidenceRawText(index, c2, { file_id: 'f1' }), 'QTY: 500 PCS')
})

test('value 自带 item_id 时优先于 comparison.item_id', () => {
  const c = { field_key: 'quantity', item_id: null }
  const v = { file_id: 'f1', item_id: 'item_002' }
  assert.equal(evidenceRawText(index, c, v), 'QTY: 500 PCS')
})

test('raw_text 也为空：如实返回 null，不编造证据', () => {
  const c = { field_key: 'volume', item_id: 'item_001' }
  assert.equal(evidenceRawText(index, c, { file_id: 'f1' }), null)
})

test('整票字段（item_id 为 null）匹配未标注归属的抽取字段', () => {
  const c = { field_key: 'invoice_no', item_id: null }
  assert.equal(evidenceRawText(index, c, { file_id: 'f1' }), 'INVOICE NO. INV-1')
})

test('商品比对对应未标注归属的唯一字段：归属无歧义，允许回退', () => {
  const ext = [{ file_id: 'f9', fields: [{ field_key: 'packages', raw_text: 'SAY ONE HUNDRED (100) CARTONS' }] }]
  const idx = buildEvidenceIndex(ext)
  const c = { field_key: 'packages', item_id: 'item_001' }
  assert.equal(evidenceRawText(idx, c, { file_id: 'f9' }), 'SAY ONE HUNDRED (100) CARTONS')
})

test('同文件同名字段多条且归属不匹配：不猜，返回 null', () => {
  const c = { field_key: 'quantity', item_id: 'item_999' }
  assert.equal(evidenceRawText(index, c, { file_id: 'f1' }), null)
})

test('文件或字段不存在：null', () => {
  const c = { field_key: 'quantity', item_id: 'item_001' }
  assert.equal(evidenceRawText(index, c, { file_id: 'fX' }), null)
  assert.equal(evidenceRawText(null, c, { file_id: 'f1' }), null)
})
