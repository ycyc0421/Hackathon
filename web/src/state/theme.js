import { ref } from 'vue'

/**
 * 主题（浅色 / 暗色）。
 *
 * 存储与解析规则：
 *   1. localStorage 里用户显式选过的主题（优先）
 *   2. 没选过就跟随系统 prefers-color-scheme，且**持续跟随**——
 *      用户在系统里切到夜间模式，页面要跟着变，不需要回来手动点一次
 *   3. 一旦用户手动选过，就停止跟随系统（显式选择优先于系统偏好）
 *
 * 主题以 `data-theme` 属性写在 <html> 上，色值全在 design-tokens.css 里。
 * 首屏防闪烁靠 index.html 里的内联脚本（在样式表之前执行），
 * 这里的 initTheme 是兜底（内联脚本被 CSP 拦掉时仍能生效）。
 */

const STORAGE_KEY = 'app.theme'

/** 当前生效的主题，供组件渲染切换按钮的状态 */
export const theme = ref('light')

/** 用户是否做过显式选择（做过就不再跟随系统） */
let userChosen = false

function systemPrefersDark() {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
}

function readSaved() {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY)
    return v === 'dark' || v === 'light' ? v : null
  } catch {
    return null
  }
}

function apply(value) {
  theme.value = value
  document.documentElement.dataset.theme = value
  // 让浏览器原生控件（滚动条、表单控件、<video> 控件条）跟随主题，
  // 否则暗色页面里会挂着一条亮色滚动条
  document.documentElement.style.colorScheme = value
}

/** 手动切换：写入存储并停止跟随系统 */
export function setTheme(value) {
  const next = value === 'dark' ? 'dark' : 'light'
  userChosen = true
  try {
    window.localStorage.setItem(STORAGE_KEY, next)
  } catch {
    /* 记不下来只影响下次进入的默认值，本次仍生效 */
  }
  apply(next)
}

export function toggleTheme() {
  setTheme(theme.value === 'dark' ? 'light' : 'dark')
}

export function initTheme() {
  const saved = readSaved()
  userChosen = saved !== null
  apply(saved ?? (systemPrefersDark() ? 'dark' : 'light'))

  // 没做过显式选择时跟随系统变化
  window
    .matchMedia?.('(prefers-color-scheme: dark)')
    .addEventListener?.('change', (e) => {
      if (userChosen) return
      apply(e.matches ? 'dark' : 'light')
    })
}
