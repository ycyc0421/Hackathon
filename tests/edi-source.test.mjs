/** EDI 上传与原件展示回归（issue #40） */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { UPLOAD_LIMITS, validateFiles, splitByName, isEdiName } from '../web/src/api/uploadLimits.js'
import { readEdiText } from '../web/src/utils/sourceFile.js'

const mkFile = (name, size = 1024) => ({ name, size })

// —— accept 白名单与扩展名识别 ——

test('accept 白名单含 .edi，且与选择器一致', () => {
  assert.ok(UPLOAD_LIMITS.accept.split(',').map((s) => s.trim()).includes('.edi'))
})

test('.edi 与 .EDI 均被识别，.txt 不被接受（大小写一致）', () => {
  assert.equal(isEdiName('invoice.edi'), true)
  assert.equal(isEdiName('INVOICE.EDI'), true)
  assert.equal(isEdiName('invoice.txt'), false)
  // 内容像 EDI 也不按内容放行——只认扩展名
  assert.equal(isEdiName('UNA:+.? '), false)
})

test('EDI 文件通过限额与同名校验，与既有类型同一套规则', () => {
  assert.deepEqual(validateFiles([mkFile('a.edi'), mkFile('b.pdf')]), [])
  const { fresh, duplicateNames } = splitByName([mkFile('a.edi')], [mkFile('a.edi', 999)])
  assert.equal(fresh.length, 0)
  assert.deepEqual(duplicateNames, ['a.edi'])
})

// —— 原件文本读取：字节保留、不解释 HTML ——

test('EDI 文本读取保留 + : ? \' 转义串与换行，不做任何改写', async () => {
  const raw = "UNA:+.? '\nIMD+F++:::CERAMIC MUG?+SET?:350ML??WHITE?'S <b>TEST</b>'"
  const file = new File([raw], 'multi-item.edi')
  assert.equal(await readEdiText(file), raw)
})

test('HTML 形似文本按普通字符读取，不执行也不转义（<script> 原样保留）', async () => {
  const raw = "FTX+AAI+++LITERALS ?+ ?: ?? ?' <script>window.__edi_probe=1</script>'"
  const file = new File([raw], 'probe.edi')
  const text = await readEdiText(file)
  assert.equal(text, raw)
  // 仅读取文本不会触碰 window / DOM，没有执行任何脚本
})

test('读取不重新编码：UTF-8 字节往返一致', async () => {
  const bytes = new TextEncoder().encode("MOA+77:4800.00'\nCNT+2:2'")
  const file = new File([bytes], 'x.edi')
  const text = await readEdiText(file)
  assert.deepEqual(new TextEncoder().encode(text), bytes)
})
