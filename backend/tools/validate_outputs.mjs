/** 校验后端返回：node tools/validate_outputs.mjs [JSON 输出目录，默认 backend/.out] */
import Ajv2020 from 'ajv/dist/2020.js'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const backendDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = resolve(backendDir, '..')
const outDir = resolve(process.argv[2] ?? join(backendDir, '.out'))
const schemaDir = join(repoRoot, 'docs', 'schema')

if (!existsSync(outDir)) {
  console.error(`输出目录不存在：${outDir}`)
  process.exit(1)
}

const ajv = new Ajv2020({ allErrors: true, strict: false })
const validateTask = ajv.compile(JSON.parse(readFileSync(join(schemaDir, 'check-task.schema.json'), 'utf8')))
const validateEval = ajv.compile(JSON.parse(readFileSync(join(schemaDir, 'evaluation.schema.json'), 'utf8')))
const files = readdirSync(outDir).filter((name) => name.endsWith('.json')).sort()
if (files.length === 0) {
  console.error(`目录里没有 JSON：${outDir}`)
  process.exit(1)
}

function consistencyProblems(task) {
  const problems = []
  const counts = {
    document_count: task.documents.length,
    field_count: task.extractions.reduce((sum, ext) => sum + ext.fields.length, 0),
    item_count: task.items.length,
    conflict_count: task.comparisons.filter((c) => c.status === 'CONFLICT').length,
    missing_count: task.comparisons.filter((c) => c.status === 'MISSING_IN_SOME').length,
    risk_count: task.risks.length,
    unrecognized_count: task.comparisons.filter((c) => c.status === 'UNRECOGNIZED').length,
  }
  for (const [key, expected] of Object.entries(counts)) {
    if (key in task.summary && task.summary[key] !== expected) {
      problems.push(`summary.${key} 为 ${task.summary[key]}，实际为 ${expected}`)
    }
  }

  const fileIds = new Set(task.documents.map((d) => d.file_id))
  const itemIds = new Set(task.items.map((item) => item.item_id))
  if (fileIds.size !== task.documents.length) problems.push('documents[].file_id 有重复')
  if (itemIds.size !== task.items.length) problems.push('items[].item_id 有重复')

  const checkFile = (id, where) => {
    if (!fileIds.has(id)) problems.push(`${where} 引用了不存在的 file_id：${id}`)
  }
  const checkItem = (id, where) => {
    if (id != null && !itemIds.has(id)) problems.push(`${where} 引用了不存在的 item_id：${id}`)
  }

  for (const ext of task.extractions) {
    checkFile(ext.file_id, 'extractions[]')
    for (const field of ext.fields) checkItem(field.item_id, 'extractions[].fields[]')
  }
  for (const cmp of task.comparisons) {
    checkItem(cmp.item_id, `comparison ${cmp.comparison_id}`)
    for (const value of cmp.values) {
      checkFile(value.file_id, `comparison ${cmp.comparison_id}`)
      checkItem(value.item_id, `comparison ${cmp.comparison_id} 的值`)
    }
  }
  for (const risk of task.risks) {
    for (const id of risk.related_file_ids ?? []) checkFile(id, `risk ${risk.risk_id}`)
    for (const id of risk.related_item_ids ?? []) checkItem(id, `risk ${risk.risk_id}`)
  }
  return problems
}

let failed = 0
for (const name of files) {
  const data = JSON.parse(readFileSync(join(outDir, name), 'utf8'))
  const isEval = name === 'evaluation.json'
  const validate = isEval ? validateEval : validateTask
  if (!validate(data)) {
    failed++
    console.log(`❌ ${name}：不符合 ${isEval ? 'Evaluation' : 'CheckTask'} Schema`)
    for (const error of validate.errors) {
      console.log(`   ${error.instancePath || '/'} ${error.message}`)
    }
    continue
  }
  const problems = isEval ? [] : consistencyProblems(data)
  if (problems.length) {
    failed += problems.length
    console.log(`❌ ${name}：${problems.join('；')}`)
  } else {
    console.log(`✅ ${name}`)
  }
}

console.log(failed ? `失败 ${failed} 项` : `全部通过（${files.length} 个结果）`)
if (failed) process.exitCode = 1
