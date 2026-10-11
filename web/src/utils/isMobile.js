/**
 * 响应式窄屏判定（模块级单例）。
 *
 * 与 CSS 移动端断点保持一致：(max-width: 640px)。
 * 用于 JS 行为层分流：窄屏下跳过高度补间、锁定对照单视图、
 * 替换拖放区文案等——CSS 只负责样式隐藏，行为差异从这里走。
 */
import { ref } from 'vue'

const mql = window.matchMedia('(max-width: 640px)')

/** 当前是否处于窄屏（手机布局）。视口跨过 640px 断点时自动更新 */
export const isMobile = ref(mql.matches)

mql.addEventListener('change', (e) => {
  isMobile.value = e.matches
})
