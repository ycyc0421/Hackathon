/**
 * timeline.mjs — 分幕剧本。
 *
 * 设计原则：**画面里的动画全部来自页面自己**。
 *
 * 剧本不重写前端动效，只做两件事：
 *   1) 像人一样操作——移动指针、悬停、按下、点击，让页面自己响应；
 *   2) 取景——决定镜头看哪里、怎么移动、何时定格。
 *
 * 所以页面切换的纸张层叠、上传页文件列表的高度收放、阶段点的脉冲、
 * 首页扫描线、按钮的描边引导，都是页面自己在播，录下来的就是用户
 * 真正会看到的东西。逐帧截图之所以能录到它们，靠的是把时间整体放慢
 * （见 overlays.mjs 的 TIME_SCALE 与 record-demo.mjs 的 CDP 播放速率），
 * 而不是把动画时长压成 0。
 *
 * 每一幕声明：
 *   prepare   进幕前只做"等元素出现 + 等画面静止"，不制造动画
 *   enter     进幕时的用户操作（点击跳转等），触发页面自身的过渡
 *   tracks    逐帧采样的取景轨道：滚动、缩放、聚焦点、光标、聚光
 *   cues      字幕卡
 *   actions   定时动作（放行后端台阶、点击）
 *
 * 两条重要约定：
 *
 * 1) 镜头与滚动都不写死像素，而是引用**元素**：
 *      focus: { ref: 'submitBtn', fx: .5, fy: .5, dx: 0, dy: 0 }
 *      scroll: { ref: 'statusRow', viewportFy: .42 }
 *    fx/fy 是元素内的相对位置（0..1），dx/dy 是附加偏移。录制时按元素
 *    实际位置解析。主 agent 改首页或样式导致布局位移时，镜头会自己跟上。
 *
 * 2) 时间轴上的时刻是**视频时间**，与渲染快慢无关。任务的阶段推进不是脚本
 *    放行的——示例数据模式下 mock 层按"创建后经过的时长"给出中间态
 *    （src/api/index.js 的 mockSnapshot），页面自己播完四个阶段。
 *    时间轴只决定"镜头此刻看向哪里"，不决定"页面此刻显示什么"。
 *
 * 3) 页面切换的过渡由**点击**触发（见 enter），剧本不再自己画转场。
 *    页面的层叠过渡约 300ms，放慢 4 倍后约 1.2s 墙钟，在 60fps 下
 *    能采到十几帧，成片里就是它原本的速度。
 */

import { lerp, sampleNumber, easingOf, OUT_W, OUT_H, quantizeClip, clipFromZoom } from './camera.mjs'

export const FPS = 60
export const FRAME_MS = 1000 / FPS

/** 元素选择器表：跨幕共用，按名字引用 */
export const SEL = {
  heroTitle: '.home-hero-title',
  heroSub: '.home-hero-sub',
  heroActions: '.home-hero-actions',
  heroBtn: '.home-hero-actions .btn.primary',
  homeStack: '.home-stack',
  dropzone: '.dropzone',
  fileList: '.file-list',
  fileItem: '.file-item',
  countryField: '.field-row .field',
  submitBtn: '.actions .btn.primary',
  statusRow: '.status-row',
  stageRow: '.stage-row',
  docList: '.doc-list',
  docItem: '.doc-item',
  statusCta: '.status-cta',
  pageHead: '.page-head',
  filterRow: '.filter-row',
  cmpItem: '.cmp-item',
  cmpHead: '.cmp-head',
  viewSwitch: '.cmp-item .view-switch',
  cmpTable: '.cmp-item .cmp-table',
  comparePane: '.cmp-item .compare-pane',
  reportHead: '.report-head',
  conclusion: '.report-conclusion',
  statRow: '.stat-row',
  docChips: '.doc-chips',
  issueList: '.issue-list',
  issueItem: '.issue-item',
  riskList: '.risk-list',
  riskItem: '.risk-item',
}

/* ── 轨道采样 ──────────────────────────────────────────────────────────── */

/** 位置轨道：值为 [x,y] 或 { ref, fx, fy, dx, dy }，逐帧解析成视口坐标 */
function samplePoints(cues, t, resolve) {
  if (!cues?.length) return resolve(null)
  if (t <= cues[0].at) return resolve(cues[0].value)
  const last = cues[cues.length - 1]
  if (t >= last.at) return resolve(last.value)
  for (let i = 0; i < cues.length - 1; i += 1) {
    const a = cues[i]
    const b = cues[i + 1]
    if (t < a.at || t > b.at) continue
    const e = easingOf(b.easing)((t - a.at) / Math.max(1, b.at - a.at))
    const pa = resolve(a.value)
    const pb = resolve(b.value)
    return [lerp(pa[0], pb[0], e), lerp(pa[1], pb[1], e)]
  }
  return resolve(last.value)
}

/** 枚举轨道（落版状态）：不插值，取 t 之前最近一条 */
function sampleEnum(cues, t) {
  if (!cues?.length) return null
  let v = cues[0].value
  for (const c of cues) {
    if (c.at > t) break
    v = c.value
  }
  return v
}

/** 字幕：文本取最近一条，mode 只在 cue 附近两帧内给出（其余帧保持稳态） */
function sampleSubtitle(cues, t) {
  if (!cues?.length) return null
  let text = { title: '', desc: '' }
  let current = null
  for (const c of cues) {
    if (c.at > t) break
    if (c.sub.title) text = { title: c.sub.title, desc: c.sub.desc ?? '' }
    current = c
  }
  if (!current) return { ...text, mode: null }
  const fresh = t - current.at < FRAME_MS * 2.5
  return { ...text, mode: fresh ? (current.sub.mode ?? null) : null }
}

/* ── 单帧采样 ──────────────────────────────────────────────────────────── */

/**
 * 采样一幕在 t（幕内毫秒）处的完整画面状态。
 * @param {object} scene
 * @param {number} t
 * @param {object} ctx 录制上下文（boxes / boxScroll / maxScroll / pressedUntil）
 */
export function sampleScene(scene, t, ctx) {
  const tr = scene.tracks ?? {}
  const boxes = ctx.boxes ?? {}
  const boxScroll = ctx.boxScroll ?? 0
  const maxScroll = ctx.maxScroll ?? 0

  /** 元素在**文档**中的位置（与当前滚动无关） */
  const docPoint = (spec) => {
    const box = boxes[spec.ref]
    if (!box) return null
    return [
      box.x + (spec.fx ?? 0.5) * box.w + (spec.dx ?? 0),
      box.y + boxScroll + (spec.fy ?? 0.5) * box.h + (spec.dy ?? 0),
    ]
  }

  // ── 滚动 ──
  // 数字 = 绝对像素；{ref, fy} = 让该元素的 fy 点落到视口的 fy 处
  const resolveScroll = (v) => {
    if (typeof v === 'number') return Math.min(Math.max(v, 0), maxScroll)
    const p = docPoint(v)
    if (!p) return 0
    return Math.min(Math.max(p[1] - (v.viewportFy ?? 0.5) * OUT_H, 0), maxScroll)
  }
  const scroll = Math.min(Math.max(sampleTrackScroll(tr.scroll, t, resolveScroll), 0), maxScroll)

  // 页面滚动后，元素在视口中上移了 scroll - boxScroll
  const delta = scroll - boxScroll
  const viewportPoint = (spec) => {
    if (!spec) return [OUT_W / 2, OUT_H / 2]
    if (Array.isArray(spec)) return [spec[0], spec[1]]
    const p = docPoint(spec)
    if (!p) return [OUT_W / 2, OUT_H / 2]
    return [p[0], p[1] - scroll]
  }

  // ── 镜头 ──
  const zoom = sampleNumber(tr.zoom, t, 1)
  const focus = samplePoints(tr.focus, t, viewportPoint)
  // 量化到整数像素：缓动插值出来的小数裁切框会让画面逐帧摆动半个像素
  // （成片里表现为内容在像素级抖动），见 camera.mjs 的 quantizeClip
  const clip = quantizeClip(clipFromZoom(zoom, focus))

  // ── 光标 ──
  const cursorPoint = samplePoints(tr.cursor, t, viewportPoint)
  const cursorVisible = sampleNumber(tr.cursorVisible, t, 1)
  // 拖拽态：true 时光标旁显示一叠纸（"手里拿着文件"）
  const dragging = tr.drag ? sampleEnum(tr.drag, t) === true : false

  // ── 聚光 ──
  const spotStrength = sampleNumber(tr.spot, t, 0)
  const spotSize = scene.spotSize ?? [640, 380]
  // 聚光遮罩同样按整数像素定位，否则柔化边缘会逐帧游移
  const spot =
    spotStrength > 0.002
      ? {
          x: Math.round(focus[0] - spotSize[0] / 2),
          y: Math.round(focus[1] - spotSize[1] / 2),
          w: spotSize[0],
          h: spotSize[1],
          pad: scene.spotPad ?? 0,
          feather: scene.spotFeather ?? 0.5,
          strength: spotStrength,
        }
      : null

  return {
    scroll,
    clip,
    cursor: {
      x: cursorPoint[0],
      y: cursorPoint[1],
      visible: cursorVisible > 0.5,
      pressed: t < (ctx.pressedUntil ?? -1),
      dragging,
    },
    sub: sampleSubtitle(scene.cues, t),
    spot,
    end: scene.endTrack ? sampleEnum(scene.endTrack, t) : 'hide',
    _focus: focus,
  }
}

/** 滚动轨道单独采样：值是数字或 {ref,fy}，混合函数对"已解析的像素值"插值 */
function sampleTrackScroll(cues, t, resolve) {
  if (!cues?.length) return 0
  const vals = cues.map((c) => ({ at: c.at, value: resolve(c.value), easing: c.easing }))
  if (t <= vals[0].at) return vals[0].value
  const last = vals[vals.length - 1]
  if (t >= last.at) return last.value
  for (let i = 0; i < vals.length - 1; i += 1) {
    const a = vals[i]
    const b = vals[i + 1]
    if (t < a.at || t > b.at) continue
    const e = easingOf(b.easing)((t - a.at) / Math.max(1, b.at - a.at))
    return lerp(a.value, b.value, e)
  }
  return last.value
}

// ═══════════════════════════════════════════════════════════════════════
// 剧本
// ═══════════════════════════════════════════════════════════════════════

export const SCENES = [
  // ── 幕一：首页 ──────────────────────────────────────────────────────
  // 页面自身的入场动画（单证散开 900ms、流程条图标依次浮现、eyebrow 脉冲）
  // 就是这一段的开场，不另外做淡入。镜头只负责取景。
  {
    id: 'home',
    label: '首页',
    durationMs: 4200,
    boxes: ['heroTitle', 'heroSub', 'heroActions', 'heroBtn', 'homeStack', 'homeSteps'],
    // 导航放在这一幕的 prepare 里：首页的入场动画（单证散开、流程条图标
    // 依次浮现）只在加载时播一次，若在帧循环之前就 goto，等循环开始时
    // 动画早已播完，开场就录不到。放在这里，加载动画正好落在第一幕的帧上。
    prepare: async (ctx) => ctx.openAndPrepare(ctx.homeUrl),
    tracks: {
      scroll: [{ at: 0, value: 0 }],
      zoom: [
        { at: 0, value: 1.0 },
        { at: 2200, value: 1.07, easing: 'easeInOutSine' },
        { at: 3000, value: 1.07 },
        { at: 4200, value: 1.0, easing: 'easeInOutSine' },
      ],
      focus: [
        { at: 0, value: { ref: 'heroTitle', fx: 0.45, fy: 0.5 } },
        { at: 2600, value: { ref: 'heroBtn', fx: 0.5, fy: 0.5 }, easing: 'easeInOutSine' },
        { at: 3000, value: { ref: 'heroBtn', fx: 0.5, fy: 0.5 } },
        { at: 4200, value: [OUT_W / 2, OUT_H / 2], easing: 'easeInOut' },
      ],
      cursor: [
        { at: 0, value: { ref: 'heroBtn', fx: 0.5, fy: 0.5, dx: 470, dy: 320 } },
        { at: 2700, value: { ref: 'heroBtn', fx: 0.5, fy: 0.5 }, easing: 'easeInOutSine' },
        { at: 3000, value: { ref: 'heroBtn', fx: 0.5, fy: 0.5 } },
      ],
      cursorVisible: [
        { at: 0, value: 0 },
        { at: 320, value: 1, easing: 'easeOut' },
      ],
      spot: [
        { at: 0, value: 0 },
        { at: 2400, value: 0.14, easing: 'easeInOut' },
        { at: 3000, value: 0.14 },
        { at: 3600, value: 0, easing: 'easeInOut' },
      ],
    },
    cues: [
      {
        at: 420,
        sub: {
          title: '多份单证，一次核对',
          desc: '发票、装箱单、提单与 EDI 报文，逐字段交叉比对',
          mode: 'in',
        },
      },
      { at: 2760, sub: { mode: 'out' } },
    ],
    // 点击「开始检查」→ 页面自己播纸张层叠切页；clickNav 不等稳定，
    // 过渡留给帧循环逐帧录（这正是"复用页面切页动画"）
    actions: [{ at: 3000, run: (ctx) => ctx.clickNav('heroBtn') }],
  },

  // ── 幕二：上传单证 ──────────────────────────────────────────────────
  {
    id: 'upload',
    label: '上传单证',
    durationMs: 6200,
    boxes: ['dropzone', 'fileList', 'fileItem', 'countryField', 'submitBtn'],
    prepare: async (ctx) => {
      // 上一幕的点击已经把页面切过来了，这里等它稳定后再量坐标
      await ctx.page.waitForSelector('.dropzone', { timeout: 20000 })
      await ctx.settleAndStabilize()
      await ctx.refresh()
    },
    tracks: {
      scroll: [{ at: 0, value: 0 }],
      zoom: [
        { at: 0, value: 1.0 },
        { at: 1500, value: 1.16, easing: 'easeInOutSine' },
        { at: 2600, value: 1.16 },
        { at: 3600, value: 1.22, easing: 'easeInOutSine' },
        { at: 5000, value: 1.18, easing: 'easeInOutSine' },
        { at: 6200, value: 1.12, easing: 'easeInOutSine' },
      ],
      focus: [
        { at: 0, value: { ref: 'dropzone', fx: 0.5, fy: 0.4 } },
        { at: 1500, value: { ref: 'dropzone', fx: 0.5, fy: 0.5 }, easing: 'easeInOutSine' },
        { at: 3700, value: { ref: 'fileList', fx: 0.5, fy: 0.5 }, easing: 'easeInOutSine' },
        { at: 6200, value: { ref: 'countryField', fx: 0.35, fy: 0.5 }, easing: 'easeInOutSine' },
      ],
      // 光标从页面右上角带着一叠纸移进拖拽区——这就是"把文件拖入"
      cursor: [
        { at: 0, value: { ref: 'dropzone', fx: 0.5, fy: 0.5, dx: 500, dy: -260 } },
        { at: 1700, value: { ref: 'dropzone', fx: 0.5, fy: 0.5, dy: -40 }, easing: 'easeInOutSine' },
        { at: 2000, value: { ref: 'dropzone', fx: 0.5, fy: 0.5 }, easing: 'easeOut' },
        { at: 2700, value: { ref: 'fileList', fx: 0.62, fy: 0.5 }, easing: 'easeInOutSine' },
        { at: 4900, value: { ref: 'countryField', fx: 0.28, fy: 0.5 }, easing: 'easeInOutSine' },
      ],
      cursorVisible: [
        { at: 0, value: 0 },
        { at: 260, value: 1, easing: 'easeOut' },
      ],
      // 拖拽态只在"手上有文件"的那段时间亮起
      drag: [
        { at: 0, value: false },
        { at: 420, value: true, easing: 'linear' },
        { at: 2100, value: false, easing: 'linear' },
      ],
      spot: [
        { at: 1200, value: 0 },
        { at: 2200, value: 0.22, easing: 'easeInOutSine' },
        { at: 4200, value: 0.22 },
        { at: 5400, value: 0.12, easing: 'easeInOutSine' },
      ],
    },
    cues: [
      {
        at: 420,
        sub: {
          title: '上传单证',
          desc: '把发票、装箱单、提单拖进来，也支持图片与 EDI 报文',
          mode: 'in',
        },
      },
      { at: 2500, sub: { title: '三份单证已就位', desc: '文件列表逐份列出，可单独移除', mode: 'in' } },
      { at: 4200, sub: { title: '选好目的国', desc: '规则集按目的国启用，这里选德国', mode: 'in' } },
      { at: 5900, sub: { mode: 'out' } },
    ],
    actions: [
      // 拿起文件 → 拖拽区高亮 → 放下。拖拽高亮、文件列表逐条收放
      // 都是页面自己的 @dragover / @drop 逻辑在跑，脚本只发事件。
      { at: 520, run: (ctx) => ctx.beginFileDrag() },
      { at: 1500, run: (ctx) => ctx.dragOverDropzone() },
      { at: 2060, run: (ctx) => ctx.dropFiles() },
      { at: 2900, run: (ctx) => ctx.refresh() },
    ],
  },

  // ── 幕三：提交检查 ──────────────────────────────────────────────────
  // 提交后任务卡整块收放进场、按钮变「处理中…」，都是页面自己的过渡
  {
    id: 'submit',
    label: '提交检查',
    durationMs: 4000,
    boxes: ['submitBtn', 'statusRow', 'stageRow', 'docList', 'docItem'],
    prepare: async (ctx) => ctx.refresh(),
    tracks: {
      scroll: [
        { at: 0, value: 0 },
        { at: 2400, value: 0 },
        { at: 3600, value: { ref: 'stageRow', viewportFy: 0.38 }, easing: 'easeInOut' },
      ],
      zoom: [
        { at: 0, value: 1.0 },
        { at: 1200, value: 1.16, easing: 'easeInOutSine' },
        { at: 2200, value: 1.16 },
        { at: 3500, value: 1.05, easing: 'easeInOutSine' },
      ],
      focus: [
        { at: 0, value: { ref: 'submitBtn', fx: 0.5, fy: 0.5, dx: 230, dy: 70 } },
        { at: 1200, value: { ref: 'submitBtn', fx: 0.5, fy: 0.5 }, easing: 'easeInOutSine' },
        { at: 2500, value: { ref: 'statusRow', fx: 0.45, fy: 0.5 }, easing: 'easeInOut' },
        { at: 4000, value: { ref: 'stageRow', fx: 0.5, fy: 0.5 }, easing: 'easeInOut' },
      ],
      cursor: [
        { at: 0, value: { ref: 'submitBtn', fx: 0.5, fy: 0.5, dx: -40, dy: -180 } },
        { at: 1100, value: { ref: 'submitBtn', fx: 0.5, fy: 0.5 }, easing: 'easeInOutSine' },
        { at: 2300, value: { ref: 'submitBtn', fx: 0.5, fy: 0.5, dx: 320, dy: 70 }, easing: 'easeInOutSine' },
      ],
      cursorVisible: [{ at: 0, value: 1 }],
      spot: [
        { at: 1500, value: 0 },
        { at: 2200, value: 0.24, easing: 'easeInOut' },
        { at: 3600, value: 0.22 },
      ],
    },
    cues: [
      { at: 300, sub: { title: '开始检查', desc: '确认目的国后提交，系统随即开工', mode: 'in' } },
      { at: 3300, sub: { mode: 'out' } },
    ],
    // 点「开始检查」提交。任务阶段不再由脚本放行——示例数据模式下
    // mock 层会按创建后经过的时长自己推进（src/api/index.js 的 mockSnapshot），
    // 所以这里只需点一下，后面几幕的推进是页面自己播的。
    actions: [
      { at: 1200, run: (ctx) => ctx.click('submitBtn') },
      { at: 2400, run: (ctx) => ctx.refresh() },
    ],
  },

  // ── 幕四：任务推进（演示重点，不跳过、不快进） ─────────────────────
  // 阶段条上活动点的脉冲、逐份文件状态的推进、解析 spinner 都是页面自己的
  {
    id: 'processing',
    label: '任务推进',
    durationMs: 11200,
    boxes: ['statusRow', 'stageRow', 'docList', 'docItem', 'statusCta'],
    prepare: async (ctx) => ctx.refresh(),
    tracks: {
      scroll: [{ at: 0, value: { ref: 'stageRow', viewportFy: 0.38 } }],
      zoom: [
        { at: 0, value: 1.06 },
        { at: 900, value: 1.22, easing: 'easeInOutSine' },
        { at: 4200, value: 1.22 },
        { at: 5000, value: 1.16, easing: 'easeInOutSine' },
        { at: 8200, value: 1.06, easing: 'easeInOut' },
        { at: 11200, value: 1.06 },
      ],
      focus: [
        { at: 0, value: { ref: 'stageRow', fx: 0.5, fy: 0.5 } },
        { at: 900, value: { ref: 'stageRow', fx: 0.5, fy: 0.5 }, easing: 'easeInOutSine' },
        { at: 5000, value: { ref: 'docList', fx: 0.5, fy: 0.55 }, easing: 'easeInOutSine' },
        { at: 8200, value: { ref: 'statusCta', fx: 0.5, fy: 0.5, dx: -130 }, easing: 'easeInOut' },
        { at: 11200, value: { ref: 'statusCta', fx: 0.5, fy: 0.5, dx: -130 } },
      ],
      cursor: [
        { at: 0, value: { ref: 'docList', fx: 0.5, fy: 0.5, dx: 350, dy: 220 } },
        { at: 1300, value: { ref: 'docList', fx: 0.62, fy: 0.5, dx: 170 }, easing: 'easeInOutSine' },
        { at: 5000, value: { ref: 'docList', fx: 0.62, fy: 0.72, dx: 110 }, easing: 'easeInOutSine' },
        { at: 8800, value: { ref: 'statusCta', fx: 0.5, fy: 0.5 }, easing: 'easeInOutSine' },
        { at: 9700, value: { ref: 'statusCta', fx: 0.5, fy: 0.5 } },
      ],
      cursorVisible: [{ at: 0, value: 1 }],
      spot: [
        { at: 0, value: 0.22 },
        { at: 7400, value: 0.22 },
        { at: 8400, value: 0.27 },
        { at: 9700, value: 0.27 },
      ],
    },
    cues: [
      {
        at: 160,
        sub: { title: '逐份解析', desc: '每份单证的状态就地推进：排队 → 解析中 → 已抽取', mode: 'in' },
      },
      { at: 3600, sub: { title: '解析进度', desc: '已处理份数实时更新，失败的会单独标出', mode: 'in' } },
      {
        at: 6600,
        sub: { title: '交叉比对', desc: '字段归一化后逐项对照，冲突与缺失分开标注', mode: 'in' },
      },
      { at: 9200, sub: { title: '结果就绪', desc: '阶段条走完，右上角按钮亮起可进入差异页', mode: 'in' } },
      { at: 10500, sub: { mode: 'out' } },
    ],
    // 这一幕没有放行动作：阶段推进、逐份文件状态、解析 spinner 全部是
    // mock 层按经过时长给出中间态后、页面自己渲染的。脚本只负责取景。
    actions: [
      { at: 8600, run: (ctx) => ctx.refresh() },
      // 点「查看待复核项」——页面自己播纸张层叠切到差异页。
      // 时机有两个约束：① 必须在任务到终态之后（示例数据模式的过程是 9s），
      // 否则按钮还是 disabled，mouse.down 落在禁用按钮上不会触发跳转；
      // ② 幕尾要留足过渡时间——--duration-page 是 300ms，但页面时间被放慢
      // K 倍，过渡本身要占掉约 1.2s 页面时间，留短了会整段落在幕外。
      { at: 9700, run: (ctx) => ctx.clickNav('statusCta') },
    ],
  },

  // ── 幕五：逐字段比对 ────────────────────────────────────────────────
  // 表格↔对照 的切换是页面自己的 crossfade + 高度过渡
  {
    id: 'diff',
    label: '逐字段比对',
    durationMs: 7000,
    boxes: ['pageHead', 'filterRow', 'cmpItem', 'cmpHead', 'viewSwitch', 'cmpTable', 'comparePane'],
    prepare: async (ctx) => {
      await ctx.page.waitForSelector('.cmp-item', { timeout: 20000 })
      await ctx.settleAndStabilize()
      await ctx.refresh()
    },
    tracks: {
      scroll: [{ at: 0, value: 0 }],
      zoom: [
        { at: 0, value: 1.0 },
        { at: 1400, value: 1.16, easing: 'easeInOutSine' },
        { at: 3000, value: 1.24, easing: 'easeInOutSine' },
        { at: 4600, value: 1.24 },
        { at: 5400, value: 1.06, easing: 'easeInOut' },
        { at: 7000, value: 1.0, easing: 'easeInOut' },
      ],
      focus: [
        { at: 0, value: { ref: 'filterRow', fx: 0.5, fy: 0.5 } },
        { at: 1400, value: { ref: 'cmpItem', fx: 0.5, fy: 0.42 }, easing: 'easeInOutSine' },
        { at: 3000, value: { ref: 'cmpItem', fx: 0.4, fy: 0.24 }, easing: 'easeInOutSine' },
        { at: 4600, value: { ref: 'cmpItem', fx: 0.5, fy: 0.5 }, easing: 'easeInOut' },
        { at: 5300, value: { ref: 'pageHead', fx: 0.5, fy: 0.5 }, easing: 'easeInOut' },
        { at: 7000, value: [OUT_W / 2, OUT_H / 2], easing: 'easeInOut' },
      ],
      cursor: [
        { at: 0, value: { ref: 'cmpItem', fx: 0.5, fy: 0.5, dx: 370, dy: 260 } },
        { at: 2300, value: { ref: 'cmpHead', fx: 0.2, fy: 0.5 }, easing: 'easeInOutSine' },
        { at: 3300, value: { ref: 'viewSwitch', fx: 0.5, fy: 0.5 }, easing: 'easeInOutSine' },
        { at: 3600, value: { ref: 'viewSwitch', fx: 0.5, fy: 0.5 } },
        { at: 4500, value: { ref: 'comparePane', fx: 0.5, fy: 0.5, dx: 160, dy: 40 }, easing: 'easeInOutSine' },
        { at: 5200, value: { ref: 'pageHead', fx: 0.5, fy: 0.5, dx: 330, dy: 200 }, easing: 'easeInOutSine' },
        { at: 7000, value: { ref: 'pageHead', fx: 0.5, fy: 0.5, dx: 330, dy: 200 } },
      ],
      cursorVisible: [{ at: 0, value: 1 }],
      spot: [
        { at: 0, value: 0 },
        { at: 1500, value: 0.24, easing: 'easeInOut' },
        { at: 3400, value: 0.24 },
        { at: 4400, value: 0.16, easing: 'easeInOut' },
        { at: 5200, value: 0.13 },
      ],
    },
    cues: [
      {
        at: 280,
        sub: { title: '逐字段比对', desc: '每张卡片列出各文件的读数，不一致的取值单独标出', mode: 'in' },
      },
      {
        at: 2400,
        sub: { title: '件数不一致', desc: '发票 100 箱，装箱单与提单 120 箱——差异一眼可见', mode: 'in' },
      },
      {
        at: 3800,
        sub: { title: '原文对照', desc: '切到并排视图，三份单证的同一字段直接对着看', mode: 'in' },
      },
      { at: 5450, sub: { mode: 'out' } },
    ],
    actions: [
      { at: 3400, run: (ctx) => ctx.clickCompareToggle() },
      // 点顶栏「报告」——页面自己播切页过渡。同样要提前，给过渡留够页面时间
      { at: 5200, run: (ctx) => ctx.clickTab('报告') },
    ],
  },

  // ── 幕六：可存档报告 ────────────────────────────────────────────────
  {
    id: 'report',
    label: '可存档报告',
    durationMs: 7000,
    boxes: ['reportHead', 'conclusion', 'statRow', 'docChips', 'issueList', 'issueItem', 'riskList', 'riskItem'],
    prepare: async (ctx) => {
      await ctx.page.waitForSelector('.report-head', { timeout: 20000 })
      await ctx.settleAndStabilize()
      await ctx.refresh()
    },
    tracks: {
      scroll: [
        { at: 0, value: 0 },
        { at: 3100, value: 0 },
        { at: 4400, value: { ref: 'issueItem', viewportFy: 0.5 }, easing: 'easeInOut' },
        { at: 5300, value: { ref: 'issueItem', viewportFy: 0.5 } },
        { at: 6300, value: { ref: 'riskItem', viewportFy: 0.52 }, easing: 'easeInOut' },
      ],
      zoom: [
        { at: 0, value: 1.0 },
        { at: 1200, value: 1.2, easing: 'easeInOutSine' },
        { at: 3000, value: 1.2 },
        { at: 4300, value: 1.12, easing: 'easeInOutSine' },
        { at: 6500, value: 1.05, easing: 'easeInOut' },
      ],
      focus: [
        { at: 0, value: { ref: 'reportHead', fx: 0.5, fy: 0.5 } },
        { at: 1200, value: { ref: 'conclusion', fx: 0.5, fy: 0.5, dy: 60 }, easing: 'easeInOutSine' },
        { at: 3000, value: { ref: 'statRow', fx: 0.5, fy: 0.5, dy: 90 }, easing: 'easeInOutSine' },
        { at: 4400, value: { ref: 'issueItem', fx: 0.5, fy: 0.5, dy: -90 }, easing: 'easeInOut' },
        { at: 6300, value: { ref: 'riskItem', fx: 0.5, fy: 0.5 }, easing: 'easeInOut' },
      ],
      cursor: [
        { at: 0, value: { ref: 'statRow', fx: 0.5, fy: 0.5, dx: 340, dy: 240 } },
        { at: 2600, value: { ref: 'statRow', fx: 0.5, fy: 0.5, dx: 180, dy: 40 }, easing: 'easeInOutSine' },
        { at: 4600, value: { ref: 'issueItem', fx: 0.5, fy: 0.5, dx: 240 }, easing: 'easeInOutSine' },
        { at: 6800, value: { ref: 'riskItem', fx: 0.5, fy: 0.5, dx: 150, dy: 40 }, easing: 'easeInOutSine' },
      ],
      cursorVisible: [{ at: 0, value: 1 }],
      spot: [
        { at: 0, value: 0 },
        { at: 1300, value: 0.22, easing: 'easeInOut' },
        { at: 4000, value: 0.22 },
        { at: 5100, value: 0.16, easing: 'easeInOut' },
      ],
    },
    cues: [
      {
        at: 280,
        sub: { title: '可存档报告', desc: '结论先于统计数字，一眼看清这次检查要不要处理', mode: 'in' },
      },
      { at: 2350, sub: { title: '本次概要', desc: '3 份文件、19 个字段，1 处不一致、1 项未校验', mode: 'in' } },
      {
        at: 4350,
        sub: { title: '需要处理的条目', desc: '每条问题列出各文件读数，可跳回差异页定位', mode: 'in' },
      },
      {
        at: 6050,
        sub: { title: '规则提示', desc: '规则命中的风险与未经校验的提示分开呈现', mode: 'in' },
      },
      { at: 6700, sub: { mode: 'out' } },
    ],
    actions: [],
  },

  // ── 幕七：落版 ──────────────────────────────────────────────────────
  {
    id: 'endcard',
    label: '落版',
    durationMs: 4200,
    boxes: [],
    prepare: async (ctx) => ctx.settleAndStabilize(),
    tracks: {
      scroll: [{ at: 0, value: { ref: 'riskItem', viewportFy: 0.52 } }],
      zoom: [
        { at: 0, value: 1.05 },
        { at: 4200, value: 1.0, easing: 'easeInOutSine' },
      ],
      focus: [{ at: 0, value: [OUT_W / 2, OUT_H / 2] }],
      cursor: [{ at: 0, value: [OUT_W / 2 + 300, OUT_H / 2 + 180] }],
      cursorVisible: [
        { at: 0, value: 1 },
        { at: 360, value: 0, easing: 'easeOut' },
      ],
      spot: [
        { at: 0, value: 0.2 },
        { at: 800, value: 0 },
      ],
    },
    cues: [],
    actions: [],
    // 落版屏是演示层，不是页面内容：页面没有"品牌落版"这一屏
    endTrack: [
      { at: 0, value: 'hide' },
      { at: 240, value: 'in' },
    ],
  },
]

/** 每一幕的绝对起始时间（视频时间） */
export const SCENE_STARTS = (() => {
  const out = []
  let acc = 0
  for (const s of SCENES) {
    out.push(acc)
    acc += s.durationMs
  }
  return out
})()

export const TOTAL_MS = SCENES.reduce((sum, s) => sum + s.durationMs, 0)

/** 封面帧：差异页对照视图落定之后（信息量最大的一屏） */
export const POSTER_MS = SCENE_STARTS[4] + 5400
