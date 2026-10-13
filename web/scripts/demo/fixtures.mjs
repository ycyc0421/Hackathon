/**
 * fixtures.mjs — 录制用的样例单证。
 *
 * 演示要真的把文件拖进上传页：Playwright 的 setInputFiles 需要真实文件路径，
 * 而"没有文件的上传页"是空壳，文件列表、逐份解析状态这些关键画面都不会出现。
 *
 * 所以这里现场生成三份最小 PDF：带文本层（内容流里有 BT/Tj 绘制操作），
 * 因此不会被上传页的"疑似扫描件"预检测命中——演示里不该出现无关警告。
 * 文件内容与 web/src/mock/check-completed.json 的文档名一一对应，
 * 上传页的逐份状态与差异页的比对结果对得上同一批单证。
 *
 * 生成到临时目录而不是仓库：仓库只留产物，不留中间文件。
 */

import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

/** 生成一份单页、带文本层的最小 PDF */
function makePdf(lines) {
  const esc = (s) => String(s).replace(/([\\()])/g, '\\$1')
  let content = 'BT /F1 16 Tf 64 742 Td 26 TL\n'
  for (const line of lines) content += `(${esc(line)}) Tj T*\n`
  content += 'ET\n'

  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
    `<< /Length ${Buffer.byteLength(content, 'latin1')} >>\nstream\n${content}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]

  let out = '%PDF-1.4\n'
  const offsets = []
  objects.forEach((body, i) => {
    offsets.push(Buffer.byteLength(out, 'latin1'))
    out += `${i + 1} 0 obj\n${body}\nendobj\n`
  })
  const xref = Buffer.byteLength(out, 'latin1')
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  for (const off of offsets) out += `${String(off).padStart(10, '0')} 00000 n \n`
  out += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(out, 'latin1')
}

/**
 * 三份样例单证。件数一项故意对不上（发票 100 箱、箱单与提单 120 箱），
 * 与示例数据里的那处冲突同源——演示里点开的就是它。
 */
const DOCS = [
  {
    name: '商业发票-INV20261012.pdf',
    lines: [
      'COMMERCIAL INVOICE',
      'Invoice No.: INV20261012',
      'Seller: NINGBO HAIYU TRADING CO., LTD.',
      'Buyer: HANSA IMPORT GMBH',
      'Country of Destination: DE',
      'HS Code: 8471.30.00',
      'Packages: 100 CTNS',
      'Net Weight: 2400 KG',
      'Total Amount: USD 48,600.00',
    ],
  },
  {
    name: '装箱单-PL20261012.pdf',
    lines: [
      'PACKING LIST',
      'Packing List No.: PL20261012',
      'Invoice No.: INV20261012',
      'Country of Destination: DE',
      'HS Code: 8471.30.00',
      'Packages: 120 CTNS',
      'Net Weight: 2400 KG',
      'Gross Weight: 2680 KG',
    ],
  },
  {
    name: '提单-BL20261012.pdf',
    lines: [
      'BILL OF LADING',
      'B/L No.: BL20261012',
      'Shipper: NINGBO HAIYU TRADING CO., LTD.',
      'Port of Loading: CNNGB',
      'Port of Discharge: DEHAM',
      'Packages: 120 CTNS',
      'Net Weight: 2400 KG',
      'Freight: PREPAID',
    ],
  },
]

/** 生成三份样例文件，返回绝对路径数组 */
export function writeSampleDocs(dir) {
  mkdirSync(dir, { recursive: true })
  return DOCS.map((doc) => {
    const path = join(dir, doc.name)
    writeFileSync(path, makePdf(doc.lines))
    return path
  })
}

export const SAMPLE_DOC_NAMES = DOCS.map((d) => d.name)
