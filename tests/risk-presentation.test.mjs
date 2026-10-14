/**
 * 风险提示展示归一化与在屏/导出衔接单测。
 *
 * 覆盖：
 * 1. CheckTask 原始风险中的重复免责前后缀剥离并转为 unverified 状态；
 * 2. 标题末尾 `（品名：xxx）` 拆分为独立的 itemScope；
 * 3. `rule_source` 中的分号拼接 HTTP(S) 链接解析为安全可点击外链（精简域名 + 完整 href），
 *    非 HTTP 协议（如 javascript: / file:）绝不生成 href；
 * 4. 内部规则集版本名（`static-source-candidates-v4`）转为可读中文；
 * 5. `visibleTaskErrors` 在已展示规则风险时过滤掉重复的 `RULES_UNVERIFIED`；
 * 6. 导出报告 `buildReportHtml` 同步清理标题中的品名尾巴并将 `rule_source` URL 渲染为链接。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  presentRisk,
  parseRuleSources,
  parseRuleSourceToken,
  visibleTaskErrors,
} from '../web/src/utils/riskPresentation.js'
import { buildReportHtml } from '../web/src/report/document.js'

test('presentRisk 剥离重复堆叠的未核实前后缀并提取商品归属与来源链接', () => {
  const rawRisk = {
    risk_id: 'rsk_1',
    type: 'OTHER',
    severity: 'WARNING',
    title: '【演示规则·未经核实】瓷制餐厨用品支持资料待人工核对（品名：陶瓷 马克杯 350ML 白）',
    detail:
      '本票目的国为 德国，HS 编码 69111000 命中瓷制餐厨用品候选规则。系统尚不支持自动确认符合性声明或测试报告的适用性、随附情况及与本商品的对应关系，请人工核对用途及原件；不作缺失或合规结论。编码来源：商业发票-INV20261017.pdf 第 1 行。（说明：本提示来自团队自拟的演示规则，来源与适用条件尚未核实，不得作为合规依据。）',
    rule_id: 'DE-CERAMICS-6911-SUPPORT-DOCS',
    rule_source:
      'https://food.ec.europa.eu/food-safety/chemical-safety/food-contact-materials/legislation_en；https://publications.europa.eu/resource/celex/01984L0500-20050520（官方来源候选；适用条件未经人工核实）',
  }

  const res = presentRisk(rawRisk)

  assert.equal(res.title, '瓷制餐厨用品支持资料待人工核对')
  assert.equal(res.itemScope, '陶瓷 马克杯 350ML 白')
  assert.equal(res.unverified, true)
  assert.equal(res.detail.includes('团队自拟的演示规则'), false)
  assert.ok(res.detail.endsWith('商业发票-INV20261017.pdf 第 1 行。'))
  assert.deepEqual(res.sources, [
    {
      text: 'food.ec.europa.eu',
      href: 'https://food.ec.europa.eu/food-safety/chemical-safety/food-contact-materials/legislation_en',
    },
    {
      text: 'publications.europa.eu',
      href: 'https://publications.europa.eu/resource/celex/01984L0500-20050520',
    },
  ])
})

test('parseRuleSources 将内部规则集版本转为可读中文，并拒绝非 HTTP(S) 链接', () => {
  const internal = parseRuleSources(
    'static-source-candidates-v4（团队自拟的演示规则，来源与适用条件未经核实）'
  )
  assert.equal(internal.hadUnverifiedSuffix, true)
  assert.deepEqual(internal.sources, [
    { text: '内置候选规则集（v4）', href: null },
  ])

  const unsafe = parseRuleSourceToken('javascript:alert(1)')
  assert.equal(unsafe.href, null)
})

test('visibleTaskErrors 在已有规则风险提示时收敛重复的 RULES_UNVERIFIED', () => {
  const errors = [
    { code: 'RULES_UNVERIFIED', message: '本票使用未经核实的规则候选…', level: 'WARNING' },
    { code: 'DOC_PARSE_FAILED', message: '提单解析失败', level: 'ERROR' },
  ]
  assert.deepEqual(visibleTaskErrors(errors, { hasRuledRisks: true }), [
    { code: 'DOC_PARSE_FAILED', message: '提单解析失败', level: 'ERROR' },
  ])
  assert.equal(visibleTaskErrors(errors, { hasRuledRisks: false }).length, 2)
})

test('buildReportHtml 将风险标题中的品名后缀收敛为归属标签，并将来源 URL 渲染为可点击外链', () => {
  const html = buildReportHtml({
    report_version: '2',
    view: 'content',
    generated_at: '2026-10-14T12:00:00Z',
    result_hash: 'a'.repeat(64),
    task: {
      task_id: 'tsk_test',
      status: 'COMPLETED',
      created_at: '2026-10-14T11:59:00Z',
      finished_at: '2026-10-14T12:00:00Z',
      input: { destination_country: 'DE', destination_country_name: '德国' },
      summary: {
        document_count: 1,
        field_count: 1,
        conflict_count: 0,
        missing_count: 0,
        risk_count: 1,
        unrecognized_count: 0,
      },
    },
    documents: [],
    items: [{ item_id: 'item_1', label: '陶瓷 马克杯 350ML 白', members: [] }],
    comparisons: [],
    risks: [
      {
        risk_id: 'rsk_1',
        type: 'HS_CLASSIFICATION',
        severity: 'WARNING',
        title: '瓷制餐厨用品食品接触用途及欧盟/成员国适用条件待核对（品名：陶瓷 马克杯 350ML 白）',
        detail: 'HS 6911 仅能提示该商品可能属于瓷制餐厨用品。',
        related_field_keys: ['hs_code'],
        related_file_ids: ['f1'],
        related_item_ids: ['item_1'],
        destination_country: 'DE',
        rule_id: 'DE-CERAMICS-6911',
        rule_source:
          'https://food.ec.europa.eu/food-safety/chemical-safety/food-contact-materials/legislation_en；https://publications.europa.eu/resource/celex/01984L0500-20050520',
        rule_context: {
          verification_status: 'UNVERIFIED',
          source_ids: [],
          applicability: null,
          definition_scope: 'CURRENT_AT_EXPORT',
        },
      },
    ],
    errors: [],
    unaligned_evidence: [],
    corrections: [],
    provenance: {
      execution_rule_version: null,
      execution_version_status: 'UNKNOWN',
      rule_verification_status: 'UNVERIFIED',
      source_metadata_scope: 'CURRENT_AT_EXPORT',
      current_definition_version: 'static-source-candidates-v4',
      monitor_mode: 'bundled_static',
      monitor_checked_at: null,
      sources: [],
      pending_updates: [],
    },
    limitations: [],
  })

  assert.equal(html.includes('（品名：陶瓷 马克杯 350ML 白）'), false, '标题末尾不再保留硬拼的品名括注')
  assert.ok(html.includes('<span class="item-scope">陶瓷 马克杯 350ML 白</span>'), '应渲染为 item-scope 标签')
  assert.ok(
    html.includes('href="https://food.ec.europa.eu/food-safety/chemical-safety/food-contact-materials/legislation_en"') &&
      html.includes('>food.ec.europa.eu</a>'),
    '来源 URL 应渲染为可点击的精简域名链接'
  )
})
