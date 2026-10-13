import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

// Node 中替换 Vite 的构建环境入口，其余均执行实际配置模块。
const source = readFileSync(new URL('../web/src/api/config.js', import.meta.url), 'utf8')
  .replace('import.meta.env.VITE_API_BASE', 'undefined')
  .replace("'./request.js'", JSON.stringify(new URL('../web/src/api/request.js', import.meta.url).href))
let sequence = 0

test('数据源参数优先于存储，禁用存储不会把示例请求变成真实请求', async (t) => {
  t.after(() => { delete globalThis.window })
  const blocked = { getItem() { throw new Error('禁止读取') }, setItem() { throw new Error('禁止写入') } }
  for (const [search, hash, storage, expected] of [
    ['', '#/', blocked, false],
    ['?mock=1', '#/', blocked, true],
    ['', '#/upload?mock=1', blocked, true],
    ['?mock=0', '#/upload?mock=1', blocked, false],
    ['', '#/', { getItem: () => '1' }, true],
  ]) {
    globalThis.window = { location: { search, hash }, localStorage: storage }
    const module = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64') + '#' + sequence++)
    assert.equal(module.isMock(), expected, search + hash)
  }
})
