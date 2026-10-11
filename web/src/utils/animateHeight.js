/**
 * 容器高度平滑过渡工具。
 *
 * 容器内增删内容导致高度变化时，只 fade 不管高度会让周围内容瞬间跳位；
 * 一律从这里走：把容器高度从旧值动画到新值（--duration-base + --ease）。
 *
 * 两种用法：
 * - animateHeight(el)：内容就地替换（状态已改、DOM 待更新），内部等
 *   nextTick 后测新高度。适用于 v-if 分支就地互换（如比对卡片表格↔对照）。
 * - captureHeight(el) + animateHeightFrom(el, fromH)：新旧内容不是同一轮
 *   DOM 更新的场景（如 out-in 切换，新内容要等旧内容离场后才插入），
 *   先记录旧高度，等新内容插入后（Transition 的 enter 钩子）再调用后者。
 *
 * prefers-reduced-motion 下全局 CSS 已把过渡时长压到 0，自然退化为瞬时。
 */
import { nextTick } from 'vue'

/** 记录容器当前高度，供稍后 animateHeightFrom 使用 */
export function captureHeight(el) {
  return el?.offsetHeight ?? null
}

/**
 * 新内容已在文档中之后，把容器高度从 fromH 平滑过渡到当前自然高度。
 * fromH 为 null 或元素不存在时静默跳过（如首屏、组件已卸载）。
 */
export function animateHeightFrom(el, fromH) {
  if (!el || fromH == null) return
  const toH = el.offsetHeight
  if (toH === fromH) return
  el.style.height = `${fromH}px`
  el.style.overflow = 'hidden'
  el.style.transition = `height var(--duration-base) var(--ease)`
  void el.offsetHeight // 强制 reflow，确立过渡起点
  el.style.height = `${toH}px`
  el.addEventListener(
    'transitionend',
    () => {
      el.style.cssText = ''
    },
    { once: true }
  )
}

/**
 * 内容就地变化的高度过渡：调用前先把响应式状态改好，本函数固定当前
 * 高度，等 nextTick 新内容上屏后测量并动画到新高度。
 */
export async function animateHeight(el) {
  if (!el) return
  const fromH = el.offsetHeight
  el.style.height = `${fromH}px`
  el.style.overflow = 'hidden'
  await nextTick()
  // 测新内容高度：固定高度下内容更矮时测不准。还原到最终态量真实高度
  // 再设回起点；测量与还原在同一帧内同步完成，不会上屏。
  el.style.cssText = ''
  const toH = el.offsetHeight
  if (toH === fromH) {
    // 高度不变不会有 transitionend，直接还原，避免内联样式残留
    el.style.cssText = ''
    return
  }
  el.style.height = `${fromH}px`
  el.style.overflow = 'hidden'
  el.style.transition = `height var(--duration-base) var(--ease)`
  void el.offsetHeight // 强制 reflow，确立过渡起点
  el.style.height = `${toH}px`
  el.addEventListener(
    'transitionend',
    () => {
      el.style.cssText = ''
    },
    { once: true }
  )
}
