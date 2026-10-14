/** 原文预览抽屉回归：类型判定 + 文本读取（与 EDI 原件同一口径） */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { UPLOAD_LIMITS } from '../web/src/api/uploadLimits.js'
import { sourceKind, readTextSource, readEdiText } from '../web/src/utils/sourceFile.js'
import { SOURCE_PREVIEW_TEXT, EDI_SOURCE_TEXT } from '../web/src/api/labels.js'

// —— 类型判定：只认扩展名，覆盖上传白名单全部格式 ——

test('白名单内的格式都能给出预览类型，不在白名单内的落 other', () => {
  // accept: .pdf,.png,.jpg,.jpeg,.webp,.json,.edi
  assert.equal(sourceKind('发票.pdf'), 'pdf')
  assert.equal(sourceKind('扫描件.PDF'), 'pdf')
  assert.equal(sourceKind('照片.png'), 'image')
  assert.equal(sourceKind('照片.jpg'), 'image')
  assert.equal(sourceKind('照片.JPEG'), 'image')
  assert.equal(sourceKind('照片.webp'), 'image')
  assert.equal(sourceKind('报文.edi'), 'text')
  assert.equal(sourceKind('报文.EDI'), 'text')
  assert.equal(sourceKind('导出.json'), 'text')
  // 前端不认识的：不猜内容
  assert.equal(sourceKind('神秘文件.xyz'), 'other')
  assert.equal(sourceKind('无扩展名'), 'other')
  assert.equal(sourceKind(''), 'other')
  assert.equal(sourceKind(null), 'other')
  assert.equal(sourceKind(undefined), 'other')
  // 浏览器给的 MIME 不可靠，判定只认扩展名——.txt 不在白名单
  assert.equal(sourceKind('文本文档.txt'), 'other')
})

test('类型判定与上传白名单一致：accept 里的每种扩展名都有非 other 的预览类型', () => {
  const exts = UPLOAD_LIMITS.accept.split(',').map((s) => s.trim().replace('.', '').toUpperCase())
  for (const ext of exts) {
    assert.notEqual(sourceKind(`x.${ext}`), 'other', `${ext} 应有预览类型`)
  }
})

// —— 文本读取：严格 UTF-8、字节保留 ——

test('readTextSource 保留 EDI 转义串与换行，不与 readEdiText 分叉', async () => {
  const raw = "UNA:+.? '\nIMD+F++:::CERAMIC MUG?+SET?:350ML??WHITE?'S'"
  const file = new File([raw], 'multi-item.edi')
  assert.equal(await readTextSource(file), raw)
  assert.equal(await readEdiText(file), raw)
})

test('readTextSource 非法 UTF-8 字节按失败抛出，不静默替换', async () => {
  const bad = new Uint8Array([0x68, 0x65, 0xff, 0x0a]) // "he" + 非法字节
  const file = new File([bad], 'broken.json')
  await assert.rejects(readTextSource(file))
})

// —— 文案：页码格式与 EDI 原件文案保持同一口径 ——

test('预览抽屉文案：页码带「第…页」，文本失败文案与 EDI 原件一致', () => {
  assert.equal(SOURCE_PREVIEW_TEXT.page(3), '第 3 页')
  assert.equal(SOURCE_PREVIEW_TEXT.textError, EDI_SOURCE_TEXT.readError)
  assert.ok(SOURCE_PREVIEW_TEXT.close.length > 0)
  assert.ok(SOURCE_PREVIEW_TEXT.unsupported.includes('下载'))
})
