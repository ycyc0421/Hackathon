/**
 * stage.mjs — 录制期的页面操作层。
 *
 * 把"点哪个元素""怎么拿坐标""怎么等页面稳定"收在这里，剧本里只写元素名。
 * 坐标每次 refresh 时按**当前滚动位置**重新测量：任务状态变化会让页面
 * 增删内容、高度改变，镜头与光标不能停在旧位置上。
 */

import { readFileSync } from 'node:fs'
import { basename } from 'node:path'
import { PULSE, PAGE_TWEAKS, INSTALL } from './overlays.mjs'

/** 光标按下态的视觉持续时长 */
const PRESS_MS = 130

/**
 * 建立录制舞台。
 * @param {import('playwright-core').Page} page
 * @param {object} boxes 元素坐标缓存（视口坐标，随 boxScroll 变化失效）
 * @param {Record<string,string>} sel 元素名 → 选择器
 * @param {string[]} sampleFiles 样例单证路径
 * @param {object} [cdp] CDP session（文件拖放用）
 */
export function createStage(page, boxes, sel, sampleFiles, cdp = null) {
  const ctx = {
    page,
    cdp,
    /** 首页地址：由入口脚本填入，第一幕的 prepare 用它导航 */
    homeUrl: '',
    boxes,
    boxScroll: 0,
    maxScroll: 0,
    pressedUntil: -1,
    now: 0,

    /** 等一次渲染落定：两帧 rAF + 一个宏任务，确保 Vue 已把 DOM 更新上屏 */
    async settle() {
      await page.evaluate(
        () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 0))))
      )
    },

    /** 等一次渲染落定并等到画面静止。切页/状态变化后必须走这个 */
    async settleAndStabilize() {
      await ctx.settle()
      await ctx.waitStable()
    },

    /**
     * 等画面真正静止：持续采样版心元素的矩形，连续若干帧不变才算稳定。
     *
     * 只等两帧 rAF 是不够的——页面切换有 300ms 的纸张层叠过渡，切页后
     * 立刻量坐标会量到过渡中间态（缩放/位移中的位置），据此点击会点空。
     * 这是实测踩过的坑：点"开始检查"没反应，页面停在首页。
     *
     * 用**帧数**而不是时间做上限：页面时间被放慢 K 倍，
     * performance.now() 也跟着缩放，按毫秒算上限会变成 K 倍长。
     */
    async waitStable(maxFrames = 240) {
      await page.evaluate(async (limit) => {
        const el = document.querySelector('.page-inner') ?? document.body
        let last = null
        let same = 0
        for (let i = 0; i < limit; i += 1) {
          const r = el.getBoundingClientRect()
          const key = [r.x, r.y, r.width, r.height].map((v) => Math.round(v * 10)).join(',')
          if (key === last) {
            same += 1
            if (same >= 3) return
          } else {
            same = 0
            last = key
          }
          await new Promise((r2) => requestAnimationFrame(r2))
        }
      }, maxFrames)
    },

    /**
     * 重新测量所有登记元素的位置与滚动范围。
     * stable=false（默认）只测当前状态，不等待——测量本身不该消耗时间；
     * 需要"画面已停"的场合由调用方先 settleAndStabilize()。
     */
    async refresh({ stable = false } = {}) {
      if (stable) await ctx.waitStable()
      const measured = await page.evaluate((selectors) => {
        const out = { boxes: {}, scrollY: window.scrollY, maxScroll: 0 }
        const doc = document.documentElement
        out.maxScroll = Math.max(0, doc.scrollHeight - window.innerHeight)
        for (const [name, selector] of Object.entries(selectors)) {
          const el = document.querySelector(selector)
          if (!el) continue
          const r = el.getBoundingClientRect()
          out.boxes[name] = { x: r.x, y: r.y, w: r.width, h: r.height }
        }
        return out
      }, sel)
      Object.assign(boxes, measured.boxes)
      ctx.boxScroll = measured.scrollY
      ctx.maxScroll = measured.maxScroll
    },

    /** 元素中心的视口坐标（按当前滚动实时测，不用缓存；先等画面静止） */
    async centerOf(selector, { stable = true } = {}) {
      if (stable) await ctx.waitStable()
      const p = await page.evaluate((s) => {
        const el = document.querySelector(s)
        if (!el) return null
        const b = el.getBoundingClientRect()
        return { x: b.x + b.width / 2, y: b.y + b.height / 2 }
      }, selector)
      if (!p) throw new Error(`找不到元素：${selector}`)
      return p
    },

    /**
     * 移到坐标 → 涟漪 → 真实按下抬起。页面据此触发 :hover / :active。
     *
     * 【关键】点完**不**等画面静止。等稳定会把页面接下来的过渡整段消耗掉
     * （点「开始检查」后的纸张层叠约 300ms 页面时间），等回到帧循环时过渡
     * 已经播完，成片里就只剩硬切——这是实测踩过的坑，也正是"没有复用页面
     * 切页动画"的根因。这里只等两帧让点击事件上屏，随后立刻返回，
     * 由帧循环按页面时钟把过渡逐帧录下来。
     */
    async pressAt(selector, { settleAfter = true } = {}) {
      // 坐标现测即可，**不**等画面静止：首页有 12s 的浮动循环动画，
      // 等稳定会把 waitStable 的整个帧预算（数秒页面时间）烧光，
      // 结果是点击后的切页过渡被"跳过"——这正是过渡录不全的原因。
      // 目标元素在布局上是静止的，现测坐标足够准。
      const p = await ctx.centerOf(selector, { stable: false })
      await page.mouse.move(p.x, p.y)
      await ctx.settle()
      ctx.pressedUntil = ctx.now + PRESS_MS
      await page.evaluate(PULSE)
      await page.mouse.down()
      await ctx.settle()
      await page.mouse.up()
      if (settleAfter) await ctx.settle()
    },

    /** 按元素名点击（普通交互，之后可以等稳定） */
    async click(name) {
      await ctx.pressAt(sel[name])
    },

    /**
     * 触发页面切换的点击。返回后**不要**再等画面静止：
     * 页面自己的层叠过渡要留给帧循环逐帧录。
     */
    async clickNav(name) {
      await ctx.pressAt(sel[name], { settleAfter: false })
    },

    /** 按元素名悬停（只移动指针，触发 :hover） */
    async hover(name) {
      const p = await ctx.centerOf(sel[name])
      await page.mouse.move(p.x, p.y)
      await ctx.settle()
    },

    /**
     * 差异页第一张卡片的「对照」分段。
     *
     * 注意不能写 `button:nth-child(2)`：ViewSwitch 的第一个子元素是
     * 滑动 pill（<span class="view-switch-pill">），按钮并不是 nth-child(2)
     * 的那个，按序号选会点到别的按钮上（实测点成了「表格」）。
     * 按 role=group 里的按钮文案选，结构变化也不受影响。
     */
    clickCompareToggle: () => ctx.pressAt('.cmp-item .view-switch button[aria-pressed="false"]'),

    /** 顶栏页签（按文案匹配：选择器语法无法按文本选）。同样不等稳定 */
    async clickTab(label, { settleAfter = false } = {}) {
      const p = await page.evaluate((text) => {
        const el = [...document.querySelectorAll('.tab')].find((e) => e.textContent.trim().startsWith(text))
        if (!el) return null
        const b = el.getBoundingClientRect()
        return { x: b.x + b.width / 2, y: b.y + b.height / 2 }
      }, label)
      if (!p) throw new Error(`找不到页签：${label}`)
      await page.mouse.move(p.x, p.y)
      await ctx.settle()
      ctx.pressedUntil = ctx.now + PRESS_MS
      await page.evaluate(PULSE)
      await page.mouse.down()
      await ctx.settle()
      await page.mouse.up()
      if (settleAfter) await ctx.settleAndStabilize()
    },

    /** 触发涟漪（不移动指针） */
    pulse: () => page.evaluate(PULSE),

    /**
     * 打开某个地址并把演示层准备好。
     *
     * 首页的入场动画（三张单证散开 900ms、流程条图标依次浮现、eyebrow 脉冲）
     * 只在页面加载时播一次。所以**不能**在帧循环之前就 goto——那样等循环
     * 开始时动画早播完了，成片里看不到开场。把导航放在第一幕的 prepare 里，
     * 加载动画就正好落在第一幕的帧上，录到的仍是页面自己的动画。
     */
    async openAndPrepare(url) {
      await page.goto(url, { waitUntil: 'domcontentloaded' })
      await page.waitForSelector('.home-hero-title', { timeout: 20000 })
      await page.addStyleTag({ content: 'html { scroll-behavior: auto !important; }' })
      await page.evaluate(PAGE_TWEAKS)
      await page.evaluate(INSTALL)
    },


    /**
     * 把样例单证交给上传页的真实 file input。
     * 文件列表的逐条收放动画由页面自己播，所以这里不等稳定。
     */
    async attachFiles() {
      await page.setInputFiles('.dropzone input[type=file]', sampleFiles)
      await ctx.settle()
    },

    /**
     * 拖拽入场：把样例文件的**真实字节**读进页面，构造 DataTransfer 与 File，
     * 然后派发 dragenter + dragover。
     *
     * 为什么在页面里合成 DragEvent 而不是用 CDP 的 Input.dispatchDragEvent：
     * CDP 只稳定派发 dragEnter/dragLeave，dragover 不落到元素上，页面的
     * @dragover（拖拽高亮）不会触发——实测拖拽区一直是灰的。
     * 合成事件走的是浏览器给页面派发事件的同一条路，event.dataTransfer
     * 里也是真实的 File 对象，因此页面的 @dragover / @dragleave / @drop
     * 处理逻辑全部按原样跑，高亮态也是页面自己画的。
     *
     * 文件用真实字节（不是空壳 File）：上传页会对 PDF 做文本层预检测，
     * 空文件会被判成"疑似扫描件"而弹出无关警告。
     */
    async beginFileDrag() {
      const payload = sampleFiles.map((p) => ({
        name: basename(p),
        b64: readFileSync(p).toString('base64'),
      }))
      await page.evaluate((items) => {
        const dt = new DataTransfer()
        for (const it of items) {
          const bin = atob(it.b64)
          const bytes = new Uint8Array(bin.length)
          for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i)
          dt.items.add(new File([bytes], it.name, { type: 'application/pdf' }))
        }
        window.__demoDT = dt
        const dz = document.querySelector('.dropzone')
        if (!dz) return
        for (const type of ['dragenter', 'dragover']) {
          dz.dispatchEvent(
            new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt })
          )
        }
      }, payload)
      await ctx.settle()
    },

    /** 在拖拽区上方维持 dragover（页面的高亮态靠它维持） */
    async dragOverDropzone() {
      await page.evaluate(() => {
        const dz = document.querySelector('.dropzone')
        if (!dz || !window.__demoDT) return
        const b = dz.getBoundingClientRect()
        dz.dispatchEvent(
          new DragEvent('dragover', {
            bubbles: true,
            cancelable: true,
            dataTransfer: window.__demoDT,
            clientX: b.x + b.width / 2,
            clientY: b.y + b.height / 2,
          })
        )
      })
    },

    /**
     * 放下文件：派发 drop，页面的 @drop 处理接住并走真实提交路径
     * （文件列表逐条收放、PDF 文本层预检都由页面自己完成）。
     */
    async dropFiles() {
      await page.evaluate(() => {
        const dz = document.querySelector('.dropzone')
        if (!dz || !window.__demoDT) return
        const b = dz.getBoundingClientRect()
        dz.dispatchEvent(
          new DragEvent('drop', {
            bubbles: true,
            cancelable: true,
            dataTransfer: window.__demoDT,
            clientX: b.x + b.width / 2,
            clientY: b.y + b.height / 2,
          })
        )
      })
      await ctx.settle()
    },

  }
  return ctx
}
