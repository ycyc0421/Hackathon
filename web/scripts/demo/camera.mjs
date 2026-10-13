/**
 * camera.mjs — 镜头模型、缓动与关键帧采样。
 *
 * 镜头状态就是一个截图裁切框（viewport 坐标，CSS px）：
 *   { x, y, w, h }
 * 输出帧恒定 1280×800。w/h 小于视口 → 截一小块再放大 → 推近。
 * 因此 clip 必须始终落在 1280×800 视口内，否则 Playwright 会报
 * 「Clipped area is outside the resulting image」。
 *
 * 分幕剧本里不直接写像素，而是写「缩放倍率 + 聚焦目标（元素选择器）」，
 * 由本模块每帧把选择器解析成视口坐标再换算成 clip。这样主 agent 改
 * 首页/样式布局时，镜头不会跟丢——脚本不需要跟着改坐标。
 */

export const OUT_W = 1280
export const OUT_H = 800

/** 全景：整个视口 */
export const FULL = Object.freeze({ x: 0, y: 0, w: OUT_W, h: OUT_H })

/** 允许的最大推近倍率。再大画面就糊了（截图是 1.5 倍设备像素） */
export const MAX_ZOOM = 1.6

// ── 缓动 ────────────────────────────────────────────────────────────────

export function linear(t) {
  return t
}

/** 起步快、落定慢。镜头"找到目标"用这个 */
export function easeOutCubic(t) {
  return 1 - (1 - t) ** 3
}

/** 两端慢、中段快。平移/滚动用这个 */
export function easeInOutCubic(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2
}

/** 更长的尾巴，适合大幅度的推近落定 */
export function easeOutQuint(t) {
  return 1 - (1 - t) ** 5
}

export function easeInOutSine(t) {
  return -(Math.cos(Math.PI * t) - 1) / 2
}

/** 轻微过冲再回正，收尾时用 */
export function easeOutBack(t) {
  const c1 = 1.70158
  const c3 = c1 + 1
  return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2
}

export const EASINGS = {
  linear,
  easeOut: easeOutCubic,
  easeInOut: easeInOutCubic,
  easeOutQuint,
  easeInOutSine,
  easeOutBack,
}

export function easingOf(name) {
  return EASINGS[name] ?? easeInOutCubic
}

// ── 插值 ────────────────────────────────────────────────────────────────

export function lerp(a, b, t) {
  return a + (b - a) * t
}

export function lerpClip(a, b, t) {
  return {
    x: lerp(a.x, b.x, t),
    y: lerp(a.y, b.y, t),
    w: lerp(a.w, b.w, t),
    h: lerp(a.h, b.h, t),
  }
}

/**
 * 量化裁切框：位置取整像素、宽高取偶数像素。
 *
 * 必须量化，否则每帧的裁切区域会落在小数像素上（缓动插值的结果），
 * Chromium 对小数裁切做的是亚像素重采样，逐帧之间同一处内容会左右
 * 摆动半个像素——成片里看起来就是"内容在像素级抖动"。
 * 宽高取偶数是为了让放大到 1280×800 的倍率是整数关系，减少重采样游移。
 */
export function quantizeClip(clip) {
  const w = Math.max(4, Math.round(clip.w / 2) * 2)
  const h = Math.max(4, Math.round(clip.h / 2) * 2)
  const x = Math.round(clip.x)
  const y = Math.round(clip.y)
  return {
    x: Math.min(Math.max(x, 0), OUT_W - w),
    y: Math.min(Math.max(y, 0), OUT_H - h),
    w,
    h,
  }
}

/** 把 clip 钳进视口：保持尺寸不变，只移动位置。尺寸恒定 → 帧序列不会被裁成异形 */
export function clampClip(clip) {
  const w = Math.min(clip.w, OUT_W)
  const h = Math.min(clip.h, OUT_H)
  return {
    w,
    h,
    x: Math.min(Math.max(clip.x, 0), OUT_W - w),
    y: Math.min(Math.max(clip.y, 0), OUT_H - h),
  }
}

/** 由「缩放倍率 + 聚焦点（视口坐标）」生成 clip，居中于聚焦点并钳位 */
export function clipFromZoom(zoom, focus = [OUT_W / 2, OUT_H / 2]) {
  const z = Math.min(Math.max(zoom, 1), MAX_ZOOM)
  const w = OUT_W / z
  const h = OUT_H / z
  return clampClip({ x: focus[0] - w / 2, y: focus[1] - h / 2, w, h })
}

// ── 关键帧采样 ──────────────────────────────────────────────────────────

/**
 * 在关键帧序列上采样。cues 必须按 at 升序，形如：
 *   [{ at: 1000, value: {...}, easing: 'easeInOut' }, ...]
 * easing 写在**区间的终点**上（描述"怎么走到这一帧"）。
 * ms 早于第一帧 → 取第一帧；晚于最后一帧 → 取最后一帧。
 *
 * @param {Array} cues
 * @param {number} ms 本幕内的相对毫秒
 * @param {(a:any,b:any,t:number)=>any} mix 值混合函数
 * @param {any} fallback 序列为空时的返回值
 */
export function sampleTrack(cues, ms, mix, fallback = null) {
  if (!cues || !cues.length) return fallback
  if (ms <= cues[0].at) return cues[0].value
  const last = cues[cues.length - 1]
  if (ms >= last.at) return last.value
  for (let i = 0; i < cues.length - 1; i += 1) {
    const a = cues[i]
    const b = cues[i + 1]
    if (ms < a.at || ms > b.at) continue
    const span = Math.max(1, b.at - a.at)
    const t = easingOf(b.easing)((ms - a.at) / span)
    return mix(a.value, b.value, t)
  }
  return last.value
}

/** 数值序列采样（滚动位置、透明度、聚光强度等） */
export function sampleNumber(cues, ms, fallback = 0) {
  return sampleTrack(cues, ms, lerp, fallback)
}

/** 镜头序列采样 */
export function sampleClip(cues, ms, fallback = FULL) {
  return sampleTrack(cues, ms, lerpClip, fallback)
}
