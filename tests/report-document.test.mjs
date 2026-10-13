/**
 * 导出 HTML 报告的回归：排版可以变，"不能把没查到呈现为通过"不能变。
 *
 * 夹具 `fixtures/report-content-samples.json` 是**后端真实生成的** content 视图
 * 响应（由 backend/app/report_content.py 跑 docs/fixtures/result 得到），
 * 不是手写的。手写夹具会随契约演进而失真，而这里要验的恰恰是"后端给什么、
 * 前端就得如实呈现什么"。
 *
 * 重点覆盖四类容易被排版顺手做错的事：
 * - 转义：商品名里带 `<b>` 是夹具里真有的，不转义就是注入；
 * - 内部标识：`item_mug`、`COMMERCIAL_INVOICE` 是机器接口的关联键，不是文案；
 * - 降级语义：未校验 / 仅一份文件 / 处理失败都不能读成"通过"；
 * - 未知历史：没记录的规则版本写"未记录"，不能用当前版本顶替。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { buildReportHtml, escapeHtml, reportFileName } from '../web/src/report/document.js'
import { comparisonCounts } from '../web/src/utils/reportConclusion.js'

const samples = JSON.parse(
  readFileSync(fileURLToPath(new URL('./fixtures/report-content-samples.json', import.meta.url)), 'utf8')
)
const render = (name) => buildReportHtml(samples[name])

/** 去掉样式与标签，取出报告正文的文字，用于断言"用户实际读到什么" */
function bodyText(html) {
  const body = html.slice(html.indexOf('<body>'))
  const stripped = body.replace(/<style[^>]*>[\s\S]*?<\/style>/g, '')
  return stripped
    .replace(/<[^>]+>/g, '\n')
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
}

test('escapeHtml 覆盖全部五个危险字符', () => {
  assert.equal(escapeHtml('<b>"x" & \'y\'</b>'), '&lt;b&gt;&quot;x&quot; &amp; &#39;y&#39;&lt;/b&gt;')
  assert.equal(escapeHtml(null), '')
  assert.equal(escapeHtml(undefined), '')
  // 0 是有效值，不能被当成空
  assert.equal(escapeHtml(0), '0')
})

test('商品名里的 HTML 被转义，不成为标签', () => {
  const html = render('check-edi-multi-item')
  const body = html.slice(html.indexOf('<body>'))
  // 夹具里的商品名是 CERAMIC MUG+SET:350ML?WHITE'S <b>TEST</b>
  assert.ok(body.includes('&lt;b&gt;TEST&lt;/b&gt;'), '应出现转义后的商品名')
  // 正文里不允许出现真的 <b> 标签（<style> 块已排除在外）
  const bodyNoStyle = body.replace(/<style[^>]*>[\s\S]*?<\/style>/g, '')
  assert.equal(/<b>/.test(bodyNoStyle), false, '不能出现未转义的 <b>')
})

test('展示文案里不出现内部 ID 与契约枚举', () => {
  for (const name of Object.keys(samples)) {
    const text = bodyText(render(name))
    for (const leak of [
      'item_mug', 'item_glass', 'item_001', // 内部商品 ID
      'COMMERCIAL_INVOICE', 'PACKING_LIST', 'BILL_OF_LADING', // doc_type 枚举
      'CONFLICT', 'SINGLE_SOURCE', 'NOT_CHECKED', 'MISSING_IN_SOME', 'UNRECOGNIZED', // 比对状态
      'ALIGNED', 'PARTIAL', 'UNALIGNED', // 对齐状态
      'LOCATED', 'UNAVAILABLE', // 证据定位状态
      'EXTRACTED', 'LOW_CONFIDENCE', 'NOT_IN_DOC', // 字段状态
      'APPLICABILITY_REVIEW_REQUIRED', // 来源适用性复核状态
      'HS_CLASSIFICATION', 'MISSING_CERTIFICATE', // 风险类型
      'CURRENT_AT_EXPORT', 'bundled_static', 'runtime_monitor', // 来源元数据范围与监测模式
      'RECORDED_IN_CORRECTION',
    ]) {
      assert.equal(text.includes(leak), false, `${name} 的正文不应出现 ${leak}`)
    }
  }
})

test('枚举译成中文：单证类型与商品名走 label', () => {
  const text = bodyText(render('check-completed'))
  assert.ok(text.includes('商业发票'), 'doc_type 应译成中文')
  assert.ok(text.includes('装箱单'))
  assert.ok(text.includes('提单'))
  assert.ok(text.includes('陶瓷马克杯'), '商品名用后端 label')
})

test('未校验项不被呈现为一致：结论与条目都要说清楚', () => {
  const text = bodyText(render('check-completed'))
  // 夹具里 cmp_6 是 NOT_CHECKED（HS 编码）
  assert.ok(text.includes('未校验'), '未校验要出现')
  assert.ok(text.includes('尚未校验'), '结论要念出未校验项')
  assert.ok(text.includes('不能判定为全部一致') || text.includes('需要人工复核'))
  assert.equal(text.includes('全部一致，'), false, '含未校验时不能宣称全部一致')
})

test('仅一份文件提供的字段与"一致"分开陈述', () => {
  const text = bodyText(render('check-completed'))
  assert.ok(text.includes('仅一份文件提供、无法交叉比对'))
  assert.ok(text.includes('不代表这些字段正确'))
  // 单独成块，不与"各文件取值一致"混在一张列表里
  assert.ok(text.indexOf('各文件取值一致') < text.indexOf('无法交叉比对'))
})

test('PARTIAL 报告带不完整前缀，且不出现绿色通过结论', () => {
  const html = render('check-partial')
  const text = bodyText(html)
  assert.ok(text.includes('本报告基于不完整的结果'))
  assert.ok(text.includes('1 份文件未能处理'))
  assert.equal(/report-head tone-ok/.test(html), false, 'PARTIAL 不能是绿色页头')
  assert.equal(/notice tone-ok/.test(html), false, 'PARTIAL 不能出现绿色确认条')
})

test('FAILED 报告：红色页头，且不出现"没有需要人工处理的条目"绿色确认', () => {
  const html = render('check-edi-unsupported')
  const text = bodyText(html)
  assert.ok(/report-head tone-bad/.test(html), 'FAILED 应为红色页头')
  assert.ok(text.includes('本次检查失败'))
  assert.ok(text.includes('本次未产生任何比对条目'))
  assert.ok(text.includes('没有比对条目不等于没有问题'))
  // 整份文件里不能有绿色确认条——失败报告里的绿色会被读成"没问题"
  assert.equal(/notice tone-ok/.test(html), false, 'FAILED 不应出现绿色确认条')
})

test('零比对条目时仍给出文件处理状态，不伪造通过', () => {
  const text = bodyText(render('check-edi-unsupported'))
  assert.ok(text.includes('格式不支持'))
  assert.ok(text.includes('暂不支持此文件格式'), '失败原因要能看到')
  assert.ok(text.includes('严重'), 'FATAL 级错误要出现')
})

test('历史规则版本未记录时写"未记录"，不用当前版本回填', () => {
  const text = bodyText(render('check-completed'))
  assert.ok(text.includes('未记录'), '要如实说未记录')
  assert.ok(text.includes('原任务未记录当时使用的规则版本'))
  // 当前定义版本是另一回事，可以显示，但不能冒充"执行时"的版本
  assert.ok(text.includes('当前规则定义版本'))
  assert.ok(text.includes('导出时的当前信息'))
})

test('未核实的风险不被写成"已核实"', () => {
  const text = bodyText(render('check-completed'))
  assert.ok(text.includes('核实状态未知') || text.includes('未经人工核实'))
  assert.equal(text.includes('已核实'), false, '契约里没有"已核实"这一档')
})

test('规则命中的风险与未经规则校验的提示分开两张卡', () => {
  const text = bodyText(render('check-completed'))
  assert.ok(text.includes('依据规则的提示'))
  assert.ok(text.includes('未经规则校验的提示'))
  assert.ok(text.indexOf('依据规则的提示') < text.indexOf('未经规则校验的提示'))
})

test('证据缺失时如实标注，不猜一条原文', () => {
  const text = bodyText(render('check-partial'))
  assert.ok(text.includes('未定位到原文片段'), '后端没给证据时要如实说明')
})

test('多品名行组带对齐状态，行号说明是文件内行号', () => {
  const text = bodyText(render('check-edi-multi-item'))
  assert.ok(text.includes('多品名行组'))
  assert.ok(text.includes('行号是各文件内的原始行号'))
  assert.ok(text.includes('按货号对齐'))
})

test('来源的 status/review_status 译成中文，且保留可追溯链接', () => {
  const html = render('check-completed-real')
  const text = bodyText(html)
  // 夹具里来源带 NOT_CHECKED 与 APPLICABILITY_REVIEW_REQUIRED
  assert.ok(text.includes('来源更新未检查'), 'source.status 要译成中文')
  assert.ok(text.includes('适用性待复核'), 'review_status 要译成中文')
  // 机构名可点，来源可追溯；url 必须保留
  assert.ok(html.includes('href="https://food.ec.europa.eu'), '来源链接要保留')
  assert.ok(text.includes('European Commission'), '用机构名而不是内部 source_id')
  assert.ok(text.includes('不等于法律适用已经核实'))
})

test('来源状态与比对/核实状态的"未校验"措辞可区分', () => {
  const text = bodyText(render('check-completed-real'))
  // 来源的 NOT_CHECKED 说的是"来源更新没查过"，不是"规则没校验"，
  // 文案必须带上"来源"二字，否则读者会与别处的"未校验"混为一谈
  assert.ok(text.includes('来源更新未检查'))
  assert.equal(text.includes('来源未校验'), false)
})

test('适用条件不把机器结构的英文键名当展示文案', () => {
  const html = render('check-completed-real')
  const text = bodyText(html)
  // 夹具的 rule_context.applicability 带这些内部键与事实代码
  for (const key of [
    'required_facts', 'hs_prefix_is_candidate_only',
    'national_implementation_review_required',
    'food_contact_use', 'test_evidence', 'market_stage', 'product_category',
  ]) {
    assert.equal(text.includes(key), false, `适用条件不应泄露内部键 ${key}`)
  }
  // 人写的 document_version 说明可以原样显示
  assert.ok(text.includes('84/500/EEC consolidated 2005-05-20'), '人写的版本说明应保留')
  assert.ok(text.includes('另有适用条件需要人工确认'), '未翻译的条件要如实说明存在')
})

test('渲染出的统计口径与 comparisonCounts 一致', () => {
  for (const [name, content] of Object.entries(samples)) {
    const counts = comparisonCounts(content.comparisons)
    const html = render(name)
    // 统计卡与结论同源，页面/导出件不会一个说 3 处一个说 2 处
    assert.ok(html.includes(`>${counts.conflict}</span><span class="stat-label">不一致`), `${name} 不一致计数应一致`)
    assert.ok(html.includes(`>${counts.single}</span><span class="stat-label">仅一份文件`), `${name} 仅一份文件计数应一致`)
  }
})

test('comparisonCounts 只认状态，缺省与未知状态不误计', () => {
  const counts = comparisonCounts([
    { status: 'MATCH' }, { status: 'CONFLICT' }, { status: 'MISSING_IN_SOME' },
    { status: 'NOT_CHECKED' }, { status: 'UNRECOGNIZED' }, { status: 'SINGLE_SOURCE' },
    { status: 'SOMETHING_NEW' }, {},
  ])
  assert.deepEqual(counts, {
    total: 8, match: 1, conflict: 1, missing: 1, unchecked: 1, unrecognized: 1, single: 1, lowConfidence: 0,
  })
  assert.deepEqual(comparisonCounts(undefined), {
    total: 0, match: 0, conflict: 0, missing: 0, unchecked: 0, unrecognized: 0, single: 0, lowConfidence: 0,
  })
})

test('输出是自包含文档：有 doctype/charset/内联样式，不引外部资源', () => {
  const html = render('check-completed')
  assert.ok(html.startsWith('<!doctype html>'))
  assert.ok(html.includes('<meta charset="utf-8">'))
  assert.ok(html.includes('<style>'), '样式必须内联')
  assert.equal(/<link[^>]+stylesheet/.test(html), false, '不能引外部样式表')
  assert.equal(/<script/.test(html), false, '导出件不应带脚本')
  assert.ok(html.includes('@media print'), '要有打印样式')
  assert.ok(html.includes('lang="zh-CN"'))
})

test('报告文件名收敛掉文件系统不友好的字符', () => {
  assert.equal(reportFileName({ task: { task_id: 'tsk_20261012_0001' } }), 'report-tsk_20261012_0001.html')
  assert.equal(reportFileName({ task: { task_id: 'a/b c' } }, 'json'), 'report-a_b_c.json')
  assert.equal(reportFileName({}), 'report-report.html')
})

test('长串（64 位结果指纹）不撑出横向滚动', () => {
  const html = render('check-completed-real')
  // 结果指纹是 64 位十六进制，等宽显示且不换行时，窄屏会被撑出横向滚动。
  // 这里守的是"等宽类必须允许断行"，不是某个具体宽度。
  assert.ok(/\.mono\s*\{[^}]*overflow-wrap:\s*anywhere/.test(html), '.mono 必须允许长串断行')
  assert.ok(/\.foot-note\s*\{[^}]*overflow-wrap:\s*anywhere/.test(html), '.foot-note 同样')
})

test('非对象入参直接报错，不产出半份报告', () => {
  assert.throws(() => buildReportHtml(null), TypeError)
  assert.throws(() => buildReportHtml('x'), TypeError)
})

test('取值一致但可信度低时，概要仍提醒复核，不显示绿色结论', () => {
  const content = structuredClone(samples['check-completed'])
  const comparison = content.comparisons.find((c) => c.status === 'MATCH')
  comparison.values[0].field_status = 'LOW_CONFIDENCE'
  content.comparisons = [comparison]
  content.risks = []
  content.task.summary.risk_count = 0
  const html = buildReportHtml(content)
  const heading = html.slice(html.indexOf('<header'), html.indexOf('</header>'))
  assert.ok(bodyText(html).includes('可信度较低'))
  assert.ok(heading.includes('需要人工复核'))
  assert.equal(heading.includes('report-head tone-ok'), false)
})

test('修正记录保留文件、原始行号、后端字段名称和状态', () => {
  const content = JSON.parse(readFileSync(new URL('../docs/fixtures/report/content.json', import.meta.url), 'utf8'))
  const change = content.corrections[0].changes[0]
  const field = { field_key: change.field_key, label: '行级件数', status: 'LOW_CONFIDENCE' }
  content.unaligned_evidence = [{ file_id: change.file_id, item_no: 7, fields: [field] }]
  content.corrections[0].changes.push({ ...structuredClone(change), item_no: 7 })
  const html = buildReportHtml(content)
  const section = html.slice(html.indexOf('<h2 class="card-title">人工修正记录'))
  const file = content.documents.find((d) => d.file_id === change.file_id)
  assert.ok(section.includes(file.file_name))
  assert.ok(section.includes('整票字段'))
  assert.ok(section.includes('第 7 行'))
  assert.ok(section.includes('行级件数'))
  assert.ok(section.includes('请核对'))
  assert.equal(section.includes('>packages<'), false)
})

test('来源只把 HTTP(S) 地址生成可点击链接', () => {
  const content = structuredClone(samples['check-completed'])
  content.provenance.sources = [{ source_id: 'source', authority: '来源名称', url: 'file:///source.html' }]
  const html = buildReportHtml(content)
  assert.ok(html.includes('来源名称'))
  assert.equal(html.includes('href="file:'), false)
})

test('报告保留后端的问题处理建议，风险未处理时不显示绿色确认', () => {
  const content = structuredClone(samples['check-completed'])
  const issue = content.comparisons.find((c) => c.status === 'CONFLICT')
  issue.suggested_action = '核对原件中的件数后再修正。'
  content.risks[0].suggested_action = '请人工确认适用条件。'
  const html = buildReportHtml(content)
  assert.ok(html.includes(issue.suggested_action))
  assert.ok(html.includes(content.risks[0].suggested_action))
  content.comparisons = content.comparisons.filter((c) => c.status === 'MATCH')
  assert.equal(buildReportHtml(content).includes('notice tone-ok'), false)
})
