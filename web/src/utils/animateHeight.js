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

/**
 * 高度补间的距离上限（px）。超过该差值时容器补间的拉扯感明显
 * （如差异页「全部 6 条 → 不一致 1 条」），改为不做高度动画、
 * 直接到位 + 内容淡入淡出，由 animateHeightAdaptive 分流。
 */
export const HEIGHT_TWEEN_MAX_DELTA = 300

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

/**
 * 页面变短后的滚动补偿：内容大高度差交换（见 animateHeightAdaptive）直接到位，
 * 若因此 window.scrollY 超出新的最大滚动位置（用户悬在半空、视口落在空白区），
 * 平滑滚动到锚点元素可见的位置——规则：锚点（筛选卡片/比对卡片）顶部对齐
 * 吸顶页头（.topbar，56px）下沿，留 8px 间隙。尊重 prefers-reduced-motion。
 */
export function compensateScrollAfterShrink(anchorEl) {
  if (!anchorEl) return
  const doc = document.documentElement
  const maxScroll = Math.max(0, doc.scrollHeight - window.innerHeight)
  if (window.scrollY <= maxScroll) return // 未悬空，不动滚动
  const topbarH = document.querySelector('.topbar')?.offsetHeight ?? 0
  const anchorTop = anchorEl.getBoundingClientRect().top + window.scrollY
  const target = Math.max(0, Math.min(anchorTop - topbarH - 8, maxScroll))
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  window.scrollTo({ top: target, behavior: reduced ? 'auto' : 'smooth' })
}

/**
 * 距离自适应的高度过渡：新旧高度差 ≤ HEIGHT_TWEEN_MAX_DELTA 时维持高度补间
 * （时长固定 --duration-base，不随距离变长）；差值过大时补间拉扯感强，
 * 不做高度动画、容器直接到位（内容的淡出淡入由各自的 Transition CSS 承担），
 * 页面变短导致悬空时做滚动补偿。
 * @param {Element|null} el 被测容器
 * @param {number|null} fromH 切换前记录的旧高度（captureHeight）
 * @param {Element|null} anchorEl 滚动补偿的锚点，缺省取 el 自身
 */
export function animateHeightAdaptive(el, fromH, anchorEl = el) {
  if (!el || fromH == null) return
  const toH = el.offsetHeight
  if (Math.abs(toH - fromH) <= HEIGHT_TWEEN_MAX_DELTA) {
    animateHeightFrom(el, fromH)
  } else {
    compensateScrollAfterShrink(anchorEl)
  }
}

/**
 * 列表条目增删的 TransitionGroup JS 钩子（上传页文件列表在用，:css="false"）。
 * 条目始终在文档流内：离场先量真实高度，再在同一时长内同步收
 * height / padding / border + 淡出——文字被自己的栏位裁掉，栏位与文字一体；
 * 兄弟行随高度收缩自然上移，不需要 move transform 补位。进入为反向。
 * 禁止 absolute 脱流方案：栏位不收缩、文字与栏位脱离、下方内容突兀上移。
 */
const listItemHeight = new WeakMap()

function clearItemInline(el) {
  el.style.cssText = ''
  listItemHeight.delete(el)
}

const ITEM_TRANSITION = `height var(--duration-base) var(--ease),
    padding var(--duration-base) var(--ease),
    border-width var(--duration-base) var(--ease),
    opacity var(--duration-base) var(--ease)`

export const heightListItemHooks = {
  onBeforeEnter(el) {
    // 元素已插入、处于自然尺寸，先记录真实高度再收起到 0
    listItemHeight.set(el, el.offsetHeight)
    el.style.height = '0px'
    el.style.paddingTop = '0'
    el.style.paddingBottom = '0'
    el.style.borderBottomWidth = '0'
    el.style.opacity = '0'
    el.style.overflow = 'hidden'
  },
  onEnter(el, done) {
    const h = listItemHeight.get(el) ?? el.offsetHeight
    void el.offsetHeight // 强制 reflow，确立过渡起点
    el.style.transition = ITEM_TRANSITION
    el.style.height = `${h}px`
    el.style.paddingTop = ''
    el.style.paddingBottom = ''
    el.style.borderBottomWidth = ''
    el.style.opacity = '1'
    el.addEventListener(
      'transitionend',
      () => {
        clearItemInline(el)
        done()
      },
      { once: true }
    )
  },
  onEnterCancelled(el) {
    clearItemInline(el)
  },
  onLeave(el, done) {
    el.style.height = `${el.offsetHeight}px`
    el.style.overflow = 'hidden'
    void el.offsetHeight // 强制 reflow，确立过渡起点
    el.style.transition = ITEM_TRANSITION
    el.style.height = '0px'
    el.style.paddingTop = '0'
    el.style.paddingBottom = '0'
    el.style.borderBottomWidth = '0'
    el.style.opacity = '0'
    el.addEventListener('transitionend', () => done(), { once: true })
  },
  onLeaveCancelled(el) {
    clearItemInline(el)
  },
}
