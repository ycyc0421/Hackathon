/**
 * overlays.mjs — 演示层：软光标、字幕卡、聚光、转场遮罩、落版。
 *
 * 这一层注入页面自己的 DOM，而不是"截完图再在 ffmpeg 里叠"：
 *   - 运镜靠截图裁切实现，注入的元素同样会被裁进去，两者天然同步；
 *   - 字体、圆角、色板与产品同源；
 *   - 不需要第二路视频，也就不需要 ffmpeg 的 overlay 滤镜树。
 *
 * 录制时**不冻结页面自身的动画**：切页的纸张层叠、上传文件列表的收放、
 * 阶段点脉冲、首页扫描线，这些都是用户真正会看到的东西，必须原样录进去。
 * 逐帧截图之所以能录到它们，靠的是把时间整体放慢（见 TIME_SCALE 与
 * record-demo.mjs 的 CDP Animation.setPlaybackRate），而不是把动画时长
 * 压成 0 —— 压成 0 等于把前端动画删掉，画面会变成一堆硬切。
 *
 * 层序（DOM 顺序即叠放顺序）：聚光 → 光标 → 字幕 → 落版。
 */

export const LAYER_ID = 'demo-layer'

/** 注入演示层容器。页面导航不会清掉它，一次注入即可 */
export const INSTALL = `
(() => {
  const ID = ${JSON.stringify(LAYER_ID)}
  if (document.getElementById(ID)) return
  const root = document.createElement('div')
  root.id = ID
  root.setAttribute('aria-hidden', 'true')
  root.innerHTML = \`
    <style>
      #\${ID} {
        position: fixed; inset: 0; pointer-events: none; z-index: 2147483000;
        --dl-ink: #101a24;
        --dl-blue: #2f6f8f;
        --dl-teal: #12857f;
        --dl-shadow: 0 12px 34px -12px rgba(15,23,32,.5), 0 2px 6px rgba(15,23,32,.16);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", "WenQuanYi Micro Hei", "Microsoft YaHei", sans-serif;
      }
      /* 聚光：中心透空、四周压暗。用 mask 表达任意矩形焦点，边缘可柔化 */
      #\${ID} .dl-spot {
        position: absolute; inset: 0; opacity: 0;
        background: rgba(8, 14, 21, .55);
        -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
        transition: opacity 620ms cubic-bezier(.4,0,.2,1) !important;
        will-change: opacity, mask-image;
      }
      /* 软光标（Playwright 截图不含系统光标，这里画一个） */
      #\${ID} .dl-cursor {
        position: absolute; left: 0; top: 0; width: 26px; height: 26px;
        opacity: 0; will-change: transform;
        transition: opacity 240ms cubic-bezier(.4,0,.2,1) !important;
      }
      #\${ID} .dl-cursor svg {
        display: block; overflow: visible;
        filter: drop-shadow(0 2px 4px rgba(15,23,32,.32));
        transition: transform 90ms cubic-bezier(.4,0,.2,1) !important;
      }
      #\${ID} .dl-cursor.dl-down svg { transform: scale(.84); }
      /* 拖拽态：光标旁带一叠纸的小角标，读起来就是"手里拿着文件" */
      #\${ID} .dl-cursor .dl-ghost {
        position: absolute; left: 16px; top: 14px; width: 46px; height: 34px;
        border-radius: 6px; opacity: 0; transform: scale(.7) rotate(-6deg);
        transform-origin: left top;
        transition: opacity 200ms cubic-bezier(.4,0,.2,1) !important,
                    transform 260ms cubic-bezier(.32,.72,0,1) !important;
      }
      #\${ID} .dl-cursor .dl-ghost i {
        position: absolute; inset: 0; display: block; border-radius: 6px;
        background: #fff; border: 1px solid rgba(15,23,32,.14);
        box-shadow: 0 6px 16px -6px rgba(15,23,32,.4);
      }
      #\${ID} .dl-cursor .dl-ghost i:nth-child(2) { transform: translate(-5px, -5px) rotate(-5deg); }
      #\${ID} .dl-cursor .dl-ghost i:nth-child(3) { transform: translate(-9px, -9px) rotate(-9deg); }
      #\${ID} .dl-cursor .dl-ghost i::after {
        content: ''; position: absolute; left: 8px; right: 8px; top: 12px; height: 2px;
        background: rgba(47,111,143,.55); border-radius: 1px;
        box-shadow: 0 6px 0 rgba(47,111,143,.3), 0 12px 0 rgba(47,111,143,.22);
      }
      #\${ID} .dl-cursor.dl-drag .dl-ghost { opacity: 1; transform: scale(1) rotate(0deg); }
      #\${ID} .dl-cursor .dl-halo {
        position: absolute; left: 13px; top: 13px; width: 26px; height: 26px;
        margin: -13px 0 0 -13px; border-radius: 50%;
        background: radial-gradient(circle, rgba(47,111,143,.45) 0%, rgba(47,111,143,0) 70%);
        opacity: 0; transform: scale(.5);
      }
      #\${ID} .dl-cursor.dl-click .dl-halo {
        animation: dl-click 620ms cubic-bezier(.2,.7,.3,1) 1 both !important;
      }
      @keyframes dl-click {
        0%   { opacity: .95; transform: scale(.4); }
        55%  { opacity: .38; transform: scale(1.8); }
        100% { opacity: 0;   transform: scale(2.4); }
      }
      /* 字幕锚点：每帧按裁切框定位（见 APPLY_FRAME），保证字幕永远在画面内。
         反向缩放抵消运镜放大，字幕在成片里的字号不随推近变化。 */
      #\${ID} .dl-sub-anchor {
        position: absolute; left: 0; bottom: 0;
        transform-origin: left bottom;
        will-change: transform, left, bottom;
      }
      /* 字幕卡 */
      #\${ID} .dl-sub {
        position: relative; max-width: 640px;
        display: flex; align-items: stretch; gap: 14px;
        padding: 15px 24px 16px 16px; border-radius: 12px;
        background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(255,255,255,.94));
        border: 1px solid rgba(15,23,32,.07);
        box-shadow: var(--dl-shadow);
        backdrop-filter: blur(12px) saturate(1.3);
        -webkit-backdrop-filter: blur(12px) saturate(1.3);
        opacity: 0; transform: translateY(20px) translateX(-12px);
        transition: opacity 360ms cubic-bezier(.4,0,.2,1) !important,
                    transform 460ms cubic-bezier(.32,.72,0,1) !important;
        will-change: opacity, transform;
      }
      #\${ID} .dl-sub.dl-in { opacity: 1 !important; transform: translateY(0) translateX(0) !important; }
      #\${ID} .dl-sub.dl-out { opacity: 0 !important; transform: translateY(-12px) !important; transition-duration: 240ms !important; }
      #\${ID} .dl-sub-bar {
        flex: none; width: 4px; border-radius: 999px;
        background: linear-gradient(180deg, var(--dl-blue), var(--dl-teal));
      }
      #\${ID} .dl-sub-body { min-width: 0; }
      #\${ID} .dl-sub-title {
        font-size: 19px; font-weight: 600; letter-spacing: .01em; line-height: 1.35; color: var(--dl-ink);
      }
      #\${ID} .dl-sub-desc { margin-top: 3px; font-size: 13.5px; line-height: 1.55; color: #55606c; }
      /* 落版 */
      #\${ID} .dl-end {
        position: absolute; inset: 0; display: flex; flex-direction: column;
        align-items: center; justify-content: center; gap: 16px; visibility: hidden;
        background: radial-gradient(120% 100% at 50% 0%, #ffffff 0%, #f1f6f8 52%, #e6eef2 100%);
        opacity: 0; transition: opacity 660ms cubic-bezier(.4,0,.2,1) !important;
      }
      #\${ID} .dl-end.dl-in { opacity: 1 !important; }
      #\${ID} .dl-end-mark { display: flex; align-items: center; gap: 15px; }
      #\${ID} .dl-end-glyph {
        width: 46px; height: 46px; border-radius: 11px; position: relative;
        background: linear-gradient(135deg, var(--dl-blue), var(--dl-teal));
        box-shadow: 0 10px 26px -10px rgba(47,111,143,.75);
      }
      #\${ID} .dl-end-glyph::before, #\${ID} .dl-end-glyph::after {
        content: ''; position: absolute; left: 12px; right: 12px; height: 3px;
        border-radius: 2px; background: rgba(255,255,255,.94);
      }
      #\${ID} .dl-end-glyph::before { top: 15px; }
      #\${ID} .dl-end-glyph::after { top: 25px; right: 19px; }
      #\${ID} .dl-end-name {
        font-size: 40px; font-weight: 600; letter-spacing: .05em; color: var(--dl-ink);
        opacity: 0; transform: translateY(14px);
        transition: opacity 640ms cubic-bezier(.4,0,.2,1) 120ms !important,
                    transform 720ms cubic-bezier(.32,.72,0,1) 120ms !important;
      }
      #\${ID} .dl-end-tag {
        font-size: 15px; color: #5b6773; letter-spacing: .16em;
        opacity: 0; transform: translateY(10px);
        transition: opacity 640ms cubic-bezier(.4,0,.2,1) 400ms !important,
                    transform 720ms cubic-bezier(.32,.72,0,1) 400ms !important;
      }
      #\${ID} .dl-end-rule {
        width: 0; height: 1px;
        background: linear-gradient(90deg, transparent, rgba(47,111,143,.6), transparent);
        transition: width 1000ms cubic-bezier(.32,.72,0,1) 560ms !important;
      }
      #\${ID} .dl-end.dl-in .dl-end-name,
      #\${ID} .dl-end.dl-in .dl-end-tag { opacity: 1 !important; transform: translateY(0) !important; }
      #\${ID} .dl-end.dl-in .dl-end-rule { width: 268px !important; }
    </style>
    <div class="dl-spot"></div>
    <div class="dl-cursor">
      <span class="dl-halo"></span>
      <span class="dl-ghost"><i></i><i></i><i></i></span>
      <svg width="26" height="26" viewBox="0 0 26 26" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M6.4 2.9 6.4 19.7 10.5 15.4 13.9 22.7 16.6 21.4 13.2 14.2 18.5 13.9Z"
              fill="#ffffff" stroke="#12202c" stroke-width="1.5" stroke-linejoin="round"/>
      </svg>
    </div>
    <div class="dl-sub-anchor">
      <div class="dl-sub">
        <span class="dl-sub-bar"></span>
        <div class="dl-sub-body"><div class="dl-sub-title"></div><div class="dl-sub-desc"></div></div>
      </div>
    </div>
    <div class="dl-end">
      <div class="dl-end-mark"><span class="dl-end-glyph"></span><span class="dl-end-name">单证校验</span></div>
      <span class="dl-end-rule"></span>
      <span class="dl-end-tag">跨境物流 · 多份单证一次核对</span>
    </div>
  \`
  document.documentElement.appendChild(root)
})()
`

/**
 * 每帧应用一次演示层状态。一次 evaluate 完成全部写入，
 * 避免一帧内多次跨进程往返。
 *
 * state = {
 *   scroll: number,
 *   cursor: { x, y, visible, pressed },
 *   sub: { title, desc, mode: 'in'|'out'|null } | null,
 *   spot: { x, y, w, h, pad, feather, strength } | null,
 *   wipe: { mode: 'fade'|'push'|'wipe', progress, from, color } | null,
 *   end: 'in'|'out'|'hide'|null,
 * }
 */
export const APPLY_FRAME = (state) => `
(() => {
  const root = document.getElementById(${JSON.stringify(LAYER_ID)})
  if (!root) return
  const s = ${JSON.stringify(state)}

  if (typeof s.scroll === 'number') window.scrollTo(0, s.scroll)

  const cur = root.querySelector('.dl-cursor')
  cur.style.transform = 'translate(' + s.cursor.x + 'px,' + s.cursor.y + 'px) translate(-50%,-50%)'
  cur.style.opacity = s.cursor.visible ? '1' : '0'
  cur.classList.toggle('dl-down', !!s.cursor.pressed)
  cur.classList.toggle('dl-drag', !!s.cursor.dragging)

  const sp = root.querySelector('.dl-spot')
  if (s.spot && s.spot.strength > 0.002) {
    const r = s.spot
    const cx = r.x + r.w / 2
    const cy = r.y + r.h / 2
    const rx = Math.max(70, r.w / 2 + (r.pad || 0))
    const ry = Math.max(56, r.h / 2 + (r.pad || 0))
    const mask = 'radial-gradient(ellipse ' + rx.toFixed(0) + 'px ' + ry.toFixed(0) + 'px at ' +
      cx.toFixed(0) + 'px ' + cy.toFixed(0) + 'px, transparent 0%, transparent ' +
      ((r.feather ?? 0.5) * 100).toFixed(0) + '%, #000 100%)'
    sp.style.webkitMaskImage = mask
    sp.style.maskImage = mask
    sp.style.opacity = String(s.spot.strength)
  } else {
    sp.style.opacity = '0'
  }

  // 字幕卡：位置跟着裁切框走（锚点反向缩放），内容按状态更新。
  // 关键：类不能每帧清掉再按 mode 重建——mode 只在 cue 附近两帧出现，
  // 其余帧是稳态，清掉就等于每帧把字幕藏起来（实测踩过的坑）。
  const sub = root.querySelector('.dl-sub')
  const anchor = root.querySelector('.dl-sub-anchor')
  if (s.sub) {
    const titleEl = sub.querySelector('.dl-sub-title')
    const nextTitle = s.sub.title || ''
    const changed = titleEl.textContent !== nextTitle
    titleEl.textContent = nextTitle
    const d = sub.querySelector('.dl-sub-desc')
    d.textContent = s.sub.desc || ''
    d.style.display = s.sub.desc ? 'block' : 'none'

    if (s.sub.mode === 'out') {
      sub.classList.add('dl-out')
      sub.classList.remove('dl-in')
    } else if (s.sub.mode === 'in' || (changed && !sub.classList.contains('dl-out'))) {
      // 新的一条字幕（或 cue 指定的入场）：重播一次滑入
      sub.classList.remove('dl-in', 'dl-out')
      void sub.offsetWidth
      sub.classList.add('dl-in')
    }
    // mode 为 null 时不碰类，保持当前显隐（稳态）
  }
  if (anchor && s.clip) {
    const zoom = s.clip.zoom || 1
    anchor.style.left = (s.clip.x + 54 / zoom).toFixed(1) + 'px'
    anchor.style.bottom = (800 - (s.clip.y + s.clip.h) + 50 / zoom).toFixed(1) + 'px'
    anchor.style.transform = 'scale(' + (1 / zoom).toFixed(4) + ')'
  }

  const end = root.querySelector('.dl-end')
  end.style.visibility = s.end === 'hide' || !s.end ? 'hidden' : 'visible'
  end.classList.toggle('dl-in', s.end === 'in')
})()
`

/** 点击涟漪：一次动画播完自己结束 */
export const PULSE = `
(() => {
  const el = document.querySelector('#${LAYER_ID} .dl-cursor')
  if (!el) return
  el.classList.remove('dl-click')
  void el.offsetWidth
  el.classList.add('dl-click')
})()
`

/**
 * 虚拟时钟。页面的「已等待 N 秒」「耗时」都按 Date.now() 差值算，而逐帧
 * 渲染的墙钟时间远长于视频时间。这个脚本必须在页面脚本之前注入
 * （Playwright 的 addInitScript），把 Date.now / new Date() 接管成
 * 「基准时间 + 视频时间」，画面上的计时才与视频进度一致。
 * 其余时间相关行为（performance.now、定时器）保持原样，不影响渲染。
 */
/**
 * 时间缩放。逐帧截图能录到页面自身动画的前提，是把时间整体放慢：
 *
 *   - 页面里 Date.now / new Date() / performance.now / rAF 时间戳 全部除以 K，
 *     于是 JS 侧的补间（上传页文件列表的高度收放、首页滚动揭示）慢下来；
 *   - CDP 的 Animation.setPlaybackRate(1/K) 让 CSS 侧的 transition/animation
 *     慢下来（见 record-demo.mjs）；
 *   - 两处同倍率，画面才是一致的慢动作，而不是两种速度打架。
 *
 * 计时器（setTimeout/setInterval）刻意**不缩放**：页面的轮询间隔、动画
 * 兜底计时器按原节奏走，录制节奏才不会变成 K 倍长。
 * 副作用：Date.now 差值算出来的「已等待 N 秒」按视频时间走（这是想要的，
 * 墙上时间跑 5 分钟而视频只有 36 秒，不缩放会显示成"已等待 25 秒"）。
 *
 * 这个脚本必须在页面脚本之前注入（Playwright 的 addInitScript）。
 */
export const TIME_SCALE = (k) => {
  const RealDate = Date
  const realNow = RealDate.now.bind(RealDate)
  const realPerf = performance.now.bind(performance)
  const t0 = realNow()
  const scaled = () => t0 + (realNow() - t0) / k

  // Date：页面用它算「已等待 N 秒」「耗时」。按放慢后的时间走，
  // 画面上的计时才与视频进度一致（墙上时间跑 2.5 分钟，视频只有 36 秒）。
  window.Date = class extends RealDate {
    constructor(...args) {
      if (args.length === 0) super(scaled())
      else super(...args)
    }
    static now() {
      return scaled()
    }
    static parse(v) {
      return RealDate.parse(v)
    }
    static UTC(...a) {
      return RealDate.UTC(...a)
    }
  }
  performance.now = () => realPerf() / k

  // 计时器一并放慢：页面里用 setTimeout 收尾的动画（animateHeight 的
  // 500ms 兜底、upload 页的时钟）必须与 CSS 动画处在同一时间尺度上，
  // 否则动画还没播完兜底就先触发，内联样式被清掉，动画会中途跳变。
  const rST = window.setTimeout
  const rSI = window.setInterval
  const rCT = window.clearTimeout
  const rCI = window.clearInterval
  const wrap = (id) => id
  window.setTimeout = (fn, ms, ...a) => wrap(rST(fn, (ms || 0) * k, ...a))
  window.setInterval = (fn, ms, ...a) => wrap(rSI(fn, (ms || 0) * k, ...a))
  window.clearTimeout = (id) => rCT(id)
  window.clearInterval = (id) => rCI(id)

  // 录制循环用它把"当前视频时间"报给页面（仅用于自检/调试）
  window.__demoTimeScale = k
  window.__demoRealNow = realNow
}

/**
 * 页面自带的动画**一律保留**，只做两件必要的收尾：
 *   1. 隐藏滚动条（截图里不该出现浏览器滚动条）；
 *   2. 关掉 caret 与滚动平滑（软光标是注入的，系统 caret 不该出现；
 *      滚动位置由剧本逐帧给，不能被 scroll-behavior:smooth 二次加工）。
 */
export const PAGE_TWEAKS = `
(() => {
  if (document.getElementById('demo-tweaks')) return
  const s = document.createElement('style')
  s.id = 'demo-tweaks'
  s.textContent = \`
    html { scrollbar-width: none !important; }
    ::-webkit-scrollbar { display: none !important; width: 0 !important; height: 0 !important; }
    * { caret-color: transparent !important; }
  \`
  document.documentElement.appendChild(s)
})()
`
