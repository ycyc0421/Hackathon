#!/usr/bin/env node
/**
 * 按 docs/schema/ 下的 JSON Schema 校验 docs/fixtures/ 里的示例数据。
 *
 * 用法：node docs/schema/validate.mjs
 * 退出码：全部通过为 0，有任一失败为 1（可用于 CI 或提交前检查）
 *
 * 用途：验证后端返回是否符合契约，无需人工逐字段比对。
 */

import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import Ajv2020 from 'ajv/dist/2020.js'

// 脚本位于 docs/schema/，仓库根在上两级
const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')

// strict: false —— schema 里用了 if/then 做跨字段约束，Ajv 严格模式会警告
const ajv = new Ajv2020({ allErrors: true, strict: false })

function load(rel) {
  return JSON.parse(readFileSync(join(root, rel), 'utf8'))
}

/** 去掉示例数据里的说明性键，它们不属于契约 */
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

const taskSchema = load('docs/schema/check-task.schema.json')
const evalSchema = load('docs/schema/evaluation.schema.json')
const validateTask = ajv.compile(taskSchema)
const validateEval = ajv.compile(evalSchema)

const cases = []

// 结果型 fixture → CheckTask
for (const name of readdirSync(join(root, 'docs/fixtures/result')).filter((f) => f.endsWith('.json'))) {
  cases.push({
    label: `docs/fixtures/result/${name}`,
    data: stripComments(load(`docs/fixtures/result/${name}`)),
    validate: validateTask,
    schemaName: 'CheckTask',
  })
}

// 单文件抽取结果 → 直接复用主 schema 的 $defs.Extraction
const extractionSchema = {
  $schema: 'https://json-schema.org/draft/2020-12/schema',
  $id: 'https://github.com/ycyc0421/Hackathon/schema/extraction.standalone.json',
  $defs: taskSchema.$defs,
  $ref: '#/$defs/Extraction',
}
const validateExtraction = ajv.compile(extractionSchema)
for (const name of readdirSync(join(root, 'docs/fixtures/raw')).filter((f) => f.endsWith('.json'))) {
  cases.push({
    label: `docs/fixtures/raw/${name}`,
    data: stripComments(load(`docs/fixtures/raw/${name}`)),
    validate: validateExtraction,
    schemaName: 'Extraction',
  })
}

// 自洽性检查：summary 的计数必须和数组实际长度对得上
function checkSummaryConsistency(data) {
  const problems = []
  if (!data.summary || !Array.isArray(data.comparisons)) return problems

  const expect = {
    document_count: data.documents?.length,
    field_count: (data.extractions ?? []).reduce((n, e) => n + (e.fields?.length ?? 0), 0),
    conflict_count: data.comparisons.filter((c) => c.status === 'CONFLICT').length,
    missing_count: data.comparisons.filter((c) => c.status === 'MISSING_IN_SOME').length,
    risk_count: data.risks?.length,
    unrecognized_count: data.comparisons.filter((c) => c.status === 'UNRECOGNIZED').length,
  }

  for (const [key, actual] of Object.entries(expect)) {
    if (data.summary[key] !== actual) {
      problems.push(`summary.${key} = ${data.summary[key]}，但实际为 ${actual}`)
    }
  }
  return problems
}

let failed = 0

for (const c of cases) {
  const ok = c.validate(c.data)
  if (ok) {
    console.log(`✅ ${c.label}  （符合 ${c.schemaName}）`)
  } else {
    failed++
    console.log(`❌ ${c.label}  （不符合 ${c.schemaName}）`)
    for (const err of c.validate.errors) {
      console.log(`     ${err.instancePath || '/'} ${err.message}`)
      if (err.params?.allowedValues) {
        console.log(`       允许值：${err.params.allowedValues.join(' / ')}`)
      }
    }
  }

  const problems = checkSummaryConsistency(c.data)
  for (const p of problems) {
    failed++
    console.log(`❌ ${c.label}  自洽性：${p}`)
  }
}

console.log()
if (failed === 0) {
  console.log(`全部通过（${cases.length} 个样例）`)
} else {
  console.log(`失败 ${failed} 项`)
  process.exitCode = 1
}
