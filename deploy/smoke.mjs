import assert from 'node:assert/strict'
import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'

const base = process.env.VITE_API_BASE
const output = process.env.SMOKE_OUTPUT_DIR
assert(base && output, '必须提供 VITE_API_BASE 和 SMOKE_OUTPUT_DIR')
await mkdir(output, { recursive: true })

async function json(path, options = {}) {
  const response = await fetch(`${base}${path}`, {
    ...options,
    headers: { Origin: origin, ...options.headers },
    signal: AbortSignal.timeout(30_000),
  })
  assert(response.ok, `${path} 返回 HTTP ${response.status}`)
  assert(['*', origin].includes(response.headers.get('access-control-allow-origin')), `${path} 的响应未允许前端跨域读取`)
  return response.json()
}

// 使用浏览器会发送的预检，确认直连后端的跨域上传能够到达应用。
assert(process.env.FRONTEND_ORIGIN, '必须提供 FRONTEND_ORIGIN')
const origin = new URL(process.env.FRONTEND_ORIGIN).origin
const preflight = await fetch(`${base}/checks`, {
  method: 'OPTIONS',
  headers: { Origin: origin, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type' },
  signal: AbortSignal.timeout(15_000),
})
assert(preflight.ok, '跨域预检失败')
assert(['*', origin].includes(preflight.headers.get('access-control-allow-origin')), '未允许前端跨域访问')
assert(preflight.headers.get('access-control-allow-methods')?.split(/,\s*/).includes('POST'), '未允许跨域 POST')

for (const [name, country, expectedStatus] of [
  ['01_us_consistent', 'US', 'COMPLETED'],
  ['02_de_conflict', 'DE', 'COMPLETED'],
  ['04_de_multiitem', 'DE', 'COMPLETED'],
]) {
  const directory = resolve('backend/samples', name)
  const form = new FormData()
  for (const file of (await readdir(directory)).filter((file) => file.endsWith('.pdf')).sort()) {
    form.append('files', new Blob([await readFile(resolve(directory, file))], { type: 'application/pdf' }), file)
  }
  form.append('destination_country', country)
  form.append('notes', '自动部署联调验证：合成单证')
  const created = await json('/checks', { method: 'POST', body: form })
  assert(created.task_id, '未返回任务编号')
  const deadline = Date.now() + 90_000
  let task
  do {
    task = await json(`/checks/${encodeURIComponent(created.task_id)}`)
    if (!['PENDING', 'PROCESSING'].includes(task.status)) break
    assert(Date.now() < deadline, '任务轮询超时')
    await sleep(1000)
  } while (true)
  assert.equal(task.status, expectedStatus, name)
  if (name === '01_us_consistent') assert.equal(task.summary.conflict_count, 0)
  if (name === '02_de_conflict') assert(task.summary.conflict_count > 0)
  if (name === '04_de_multiitem') assert(task.items.length > 1)
  await writeFile(resolve(output, `${name}.json`), JSON.stringify(task))
  console.info(`联调通过：${name}，${task.status}`)
}

const missing = await fetch(`${base}/checks/tsk_missing_deployment_probe`, { signal: AbortSignal.timeout(15_000) })
assert.equal(missing.status, 404)
assert.equal((await missing.json()).error.code, 'TASK_NOT_FOUND')
await writeFile(resolve(output, 'evaluation.json'), JSON.stringify(await json('/evaluation/latest')))
