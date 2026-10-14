/**
 * web/src/mock 下的评测夹具回归。
 *
 * 根目录 npm run validate 只扫 docs/fixtures，既不扫前端 mock，也不校验评测契约；
 * 而评测页上的每一个数字都来自这一份夹具。夹具一旦与 evaluation schema 或
 * counts↔metrics 的关系脱节，页面就会显示自相矛盾的分数——这一页的全部意义
 * 就是可信，所以两件事都固定住。
 *
 * 依赖：docs/schema/evaluation.schema.json 需已含 scope（feat/evaluation-results）。
 * 旧 schema 的根节点是 additionalProperties:false，会把 scope 判为非法属性——
 * 夹具必须与契约同批落地，不能先合前端。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import Ajv2020 from 'ajv/dist/2020.js'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const load = (rel) => JSON.parse(readFileSync(join(root, rel), 'utf8'))

/** 与 docs/schema/validate.mjs 相同：去掉说明性键，它们不属于契约 */
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
const validateEval = ajv.compile(load('docs/schema/evaluation.schema.json'))

const evalMocks = readdirSync(join(root, 'web/src/mock'))
  .filter((f) => f.startsWith('evaluation-') && f.endsWith('.json'))
  .sort()

/** 页面按 run_at 匹配当前批次，两份夹具的时间必须不同，否则选择器选中不了 */
const mock = (name) => stripComments(load(`web/src/mock/${name}`))

test('注册了评测 mock 夹具', () => {
  assert.deepEqual(evalMocks, ['evaluation-done.json', 'evaluation-scan.json'])
})

for (const name of evalMocks) {
  test(`${name} 符合 Evaluation schema`, () => {
    const ok = validateEval(mock(name))
    if (!ok) {
      assert.fail(validateEval.errors.map((e) => `${e.instancePath || '/'} ${e.message}`).join('\n'))
    }
  })
}

test('两份夹具覆盖不同输入通道与时间，批次选择器才有可选项', () => {
  const runs = evalMocks.map(mock)
  assert.deepEqual(runs.map((r) => r.status), ['DONE', 'DONE'])
  assert.equal(new Set(runs.map((r) => r.scope.input_kind)).size, runs.length, '输入通道应各不相同')
  assert.equal(new Set(runs.map((r) => r.run_at)).size, runs.length, '运行时间应各不相同')
})

/** 与 backend/app/evaluation.py 的 scores 同一口径：分母为零返回 null，不补 100% */
function scores({ tp, fp, fn }) {
  return {
    precision: tp + fp ? tp / (tp + fp) : null,
    recall: tp + fn ? tp / (tp + fn) : null,
    f1: 2 * tp + fp + fn ? (2 * tp) / (2 * tp + fp + fn) : null,
  }
}

/* 夹具的分数按展示精度保留三位小数；后端 validate_result 的容差针对真实结果，
   这里按三位小数取整比较，既固定住"算得出来"，又不要求夹具伪装成未取整的原始输出。 */
const round3 = (v) => (v === null ? null : Number(v.toFixed(3)))

for (const name of evalMocks) {
  test(`${name}：counts 能算出 metrics，且指标与计数一一对应`, () => {
    const { status, metrics, scope } = mock(name)
    assert.equal(status, 'DONE')
    assert.ok(scope?.counts, 'DONE 结果必须带 scope.counts')
    // 与后端读取端同一约束：每个计了分的指标都必须有计数
    for (const metric of Object.keys(metrics)) {
      assert.ok(scope.counts[metric], `缺少 ${metric} 的计数`)
    }
    for (const [metric, count] of Object.entries(scope.counts)) {
      for (const [key, value] of Object.entries(scores(count))) {
        assert.equal(metrics[metric][key], round3(value), `${metric}.${key}`)
      }
    }
  })

  test(`${name}：范围与页面上的其他数字不打架`, () => {
    const { scope, error_breakdown, sample_count } = mock(name)
    // document_count 是文件数、sample_count 是货票数，一票至少一份文件
    assert.ok(scope.document_count >= sample_count, 'document_count 应不小于货票数')
    // 输入通道声明非 OCR 时，错误分类里不允许出现 OCR / 扫描类目
    if (/非\s*OCR/.test(scope.input_kind)) {
      for (const key of Object.keys(error_breakdown ?? {})) {
        assert.doesNotMatch(key, /OCR|扫描/, `input_kind 为「${scope.input_kind}」时不该有分类「${key}」`)
      }
    }
    // 错误分类与计数同源（evaluate_dataset.py 的 error_breakdown 由 counts 推导）
    assert.equal(error_breakdown['字段漏读或值不符'], scope.counts.field_extraction.fn)
    assert.equal(error_breakdown['字段多读或值不符'], scope.counts.field_extraction.fp)
    assert.equal(error_breakdown['冲突漏检'], scope.counts.conflict_detection.fn)
    assert.equal(error_breakdown['冲突误报'], scope.counts.conflict_detection.fp)
  })

  test(`${name}：每个指标都有口径说明，局限说明保留"不能视为未见测试集"`, () => {
    const { metrics, scope } = mock(name)
    for (const metric of Object.keys(metrics)) {
      assert.ok(scope.metric_definitions[metric], `缺少 ${metric} 的口径说明`)
    }
    assert.ok(scope.limitations.length > 0)
    // 这一条是评测页可信度的落点：夹具不允许被删成只剩好看的说明
    assert.ok(scope.limitations.some((l) => /开发|回归/.test(l)), '局限说明必须保留数据集已用于开发的声明')
  })
}
