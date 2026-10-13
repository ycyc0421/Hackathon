import { test } from 'node:test'
import assert from 'node:assert/strict'
// 先在 Node 环境加载 Vue，再为主题逻辑提供最小浏览器存根。
import '../web/src/state/theme.js'

test('主题跟随系统，手动选择后保持并可在重新加载时恢复', async (t) => {
  const saved = new Map()
  const listeners = []
  const media = { matches: false, addEventListener: (_, fn) => listeners.push(fn) }
  globalThis.window = { matchMedia: () => media, localStorage: {
    getItem: (key) => saved.get(key), setItem: (key, value) => saved.set(key, value),
  } }
  globalThis.document = { documentElement: { dataset: {}, style: {} } }
  t.after(() => { delete globalThis.window; delete globalThis.document })
  const theme = await import('../web/src/state/theme.js?test=follow')
  theme.initTheme()
  assert.equal(theme.theme.value, 'light')
  media.matches = true
  listeners.forEach((fn) => fn({ matches: true }))
  assert.equal(theme.theme.value, 'dark')
  theme.toggleTheme()
  assert.equal(saved.get('app.theme'), 'light')
  listeners.forEach((fn) => fn({ matches: true }))
  assert.equal(theme.theme.value, 'light')
  const restored = await import('../web/src/state/theme.js?test=restore')
  restored.initTheme()
  assert.equal(restored.theme.value, 'light')
  assert.equal(document.documentElement.style.colorScheme, 'light')
})

test('主题存储被禁止时，系统偏好和本次手动切换仍可用', async (t) => {
  globalThis.window = { matchMedia: () => ({ matches: true, addEventListener() {} }), localStorage: {
    getItem() { throw new Error('禁用存储') }, setItem() { throw new Error('禁用存储') },
  } }
  globalThis.document = { documentElement: { dataset: {}, style: {} } }
  t.after(() => { delete globalThis.window; delete globalThis.document })
  const theme = await import('../web/src/state/theme.js?test=blocked')
  theme.initTheme()
  assert.equal(theme.theme.value, 'dark')
  theme.toggleTheme()
  assert.equal(document.documentElement.dataset.theme, 'light')
})
