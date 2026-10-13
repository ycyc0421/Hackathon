#!/usr/bin/env node
/**
 * record-demo.mjs — 演示视频录制入口。
 *
 * 用法（两种都行，脚本能自己把前端跑起来）：
 *   cd web && npm run record-demo
 *   cd web && npm run record-demo -- --base-url https://hackathon.ychome.net
 *
 * 参数：
 *   --base-url <url>   直接指向一个已部署的站点，跳过自启服务器
 *   --port <n>         自启服务器用的端口，默认 4173
 *   --server <mode>    preview（默认，用已构建的 dist/）| dev
 *   --start-from <n>   从第 n 幕（0 起）开始重跑，调试用，避免每次全量
 *   --fps <n>          帧率，默认 60
 *   --out <path>       输出视频路径
 *   --poster <path>    输出封面路径
 *   --preview          只渲染帧、不出片（快速看某一幕的画面）
 *   --keep-frames      保留中间帧（默认结束后清理）
 *   --headed           显示浏览器窗口（调试用）
 *
 * 环境变量（都可不设）：
 *   PLAYWRIGHT_CORE_PATH  playwright-core 的安装目录
 *   CHROMIUM_PATH         Chromium 可执行文件（不设则交给 playwright 解析）
 *   FFMPEG_PATH           ffmpeg 可执行文件
 *   DEMO_TIME_K           页面时间放慢倍率，默认 4
 *
 * 退出码：0 成功；2 前置依赖缺失；3 录制过程失败。
 *
 * ── 只模拟人，不模拟应用 ──
 *
 * 这是本脚本最重要的设计约束。脚本只做三件事：移动光标、点击/拖拽/滚动、
 * 截图。**页面里的一切都由前端自己播**——切页的纸张层叠、上传进度、
 * 文件列表收放、阶段点脉冲、CTA 描边、差异页的视图切换，脚本一个字节都不改。
 *
 * 走示例数据模式（?mock=1），不挂假后端、不拦截任何请求：
 *   - 任务阶段由 mock 层按"创建后经过的时长"推进（src/api/index.js 的
 *     mockSnapshot），页面因此会自己播完「排队中 → 解析文件中 → 交叉比对中
 *     → 已生成结果」，逐份文件也会走「已收到 → 解析中 → 已抽取」。
 *   - 走的是页面自己的场景卡入口（点首页演示场景卡 → 跳上传页 → 自动提交），
 *     与评审打开 ?mock=1 手动点一遍的路径完全一致。
 *
 * 曾经这里是相反的：脚本自带假后端按剧本放行阶段、拦截 API、改写轮询间隔，
 * 等于把前端的渲染路径在脚本里重写了一遍——成片里看不到前端真实的切页动画，
 * 而且一旦前端改版，脚本就与真实行为脱节。
 *
 * ── 页面自身的动画怎么录得下来 ──
 * 把页面时间放慢 K 倍（见 demo/overlays.mjs 的 TIME_SCALE 与 CDP 的
 * Animation.setPlaybackRate），并按页面时钟取帧，让"一帧 = 1/fps 秒页面时间"，
 * 动画在成片里保持原本的速度。
 */

import { parseArgs } from 'node:util'
import { mkdirSync, rmSync, existsSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { writeSampleDocs, SAMPLE_DOC_NAMES } from './demo/fixtures.mjs'
import { createStage } from './demo/stage.mjs'
import { renderFrames, encode, makePoster } from './demo/record.mjs'
import { APPLY_FRAME, TIME_SCALE } from './demo/overlays.mjs'
import { SCENES, SCENE_STARTS, TOTAL_MS, FPS, POSTER_MS, SEL } from './demo/timeline.mjs'
import { OUT_W, OUT_H } from './demo/camera.mjs'
import {
  EXIT, PreflightError, fail, loadPlaywright, resolveChromiumPath, browserHint,
  resolveFfmpeg, startServer, registerCleanup,
} from './demo/env.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const WEB_DIR = resolve(HERE, '..')
const PUBLIC_DIR = join(WEB_DIR, 'public')

/** 中间产物放临时目录（尊重 TMPDIR），不往仓库里塞 */
const WORK_DIR = join(process.env.TMPDIR || '/tmp', 'hackathon-demo-record')

const { values: argv } = parseArgs({
  options: {
    'base-url': { type: 'string', default: '' },
    port: { type: 'string', default: '4173' },
    server: { type: 'string', default: 'preview' },
    'start-from': { type: 'string', default: '0' },
    fps: { type: 'string', default: String(FPS) },
    out: { type: 'string', default: join(PUBLIC_DIR, 'demo.mp4') },
    poster: { type: 'string', default: join(PUBLIC_DIR, 'demo-poster.jpg') },
    preview: { type: 'boolean', default: false },
    'keep-frames': { type: 'boolean', default: false },
    headed: { type: 'boolean', default: false },
  },
  strict: false,
})

const START_FROM = Math.max(0, Math.min(SCENES.length - 1, Number.parseInt(argv['start-from'], 10) || 0))
const FPS_ARG = Number.parseInt(argv.fps, 10) || FPS
const OUT_FILE = resolve(argv.out)
const POSTER_FILE = resolve(argv.poster)
const FRAMES_DIR = join(WORK_DIR, 'frames')

/**
 * 时间缩放倍率。页面自身动画最短的一档是 --duration-fast = 120ms，
 * 放慢 4 倍后约 480ms 墙钟，60fps 下能采到约 29 帧，成片里是它原本的
 * 速度（120ms 页面时间）。再大就只是徒增录制时间。
 */
const TIME_K = Number.parseFloat(process.env.DEMO_TIME_K ?? '4')

/** 录制期的轮询间隔（ms）。只影响录制，不改仓库源码，见下方路由拦截 */

function log(msg) {
  process.stdout.write(`${msg}\n`)
}

async function main() {
  log('\n▶ 演示视频录制')
  log(`  视频 ${OUT_W}×${OUT_H} @ ${FPS_ARG}fps，共 ${(TOTAL_MS / 1000).toFixed(1)}s`)
  log(`  页面时间放慢 ${TIME_K}×（动画按原速播，逐帧采到连续的真实状态）`)

  // ── 前置检查：缺什么就明确说清怎么装，然后以非零码退出 ──
  const ffmpeg = resolveFfmpeg()
  log(`  ffmpeg：${ffmpeg}`)
  const { mod: playwright, from } = await loadPlaywright()
  const { chromium } = playwright
  log(`  playwright-core：${from}`)
  const chromiumPath = resolveChromiumPath()
  log(`  Chromium：${chromiumPath ?? '交给 playwright 解析'}`)

  // ── 前端：优先用已部署站点，否则自己起停 ──
  registerCleanup([])
  let server = null
  let baseUrl = argv['base-url'] ? argv['base-url'].replace(/\/$/, '') : ''
  if (!baseUrl) {
    server = await startServer({
      webDir: WEB_DIR,
      port: Number.parseInt(argv.port, 10) || 4173,
      prefer: argv.server === 'dev' ? 'dev' : 'preview',
      log,
    })
    baseUrl = server.url
    registerCleanup([() => server.stop()])
  } else {
    log(`  使用已部署站点：${baseUrl}`)
    const ok = await fetch(baseUrl).then((r) => r.ok || r.status < 500).catch(() => false)
    if (!ok) {
      throw new PreflightError(
        `无法访问 ${baseUrl}`,
        '确认地址可达；离线环境请去掉 --base-url，让脚本用本地 vite preview 自起服务'
      )
    }
  }

  const sampleFiles = writeSampleDocs(join(WORK_DIR, 'docs'))
  log(`  样例单证：${SAMPLE_DOC_NAMES.join('、')}`)

  let browser
  try {
    browser = await chromium.launch({
      // 不传路径时由 playwright 自己解析浏览器；解析不到再退回本机缓存
      ...(chromiumPath ? { executablePath: chromiumPath } : {}),
      headless: !argv.headed,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--hide-scrollbars',
        '--force-color-profile=srgb',
        '--disable-lcd-text',
        '--font-render-hinting=none',
        // 逐帧截图靠软件光栅更稳，也不需要 GPU
        '--disable-gpu',
      ],
    })
  } catch (err) {
    throw new PreflightError(`启动浏览器失败：${err.message}`, browserHint(err))
  }
  registerCleanup([() => browser.close().catch(() => {})])

  const context = await browser.newContext({
    viewport: { width: OUT_W, height: OUT_H },
    deviceScaleFactor: 1.5, // 推近后画面不被放大糊掉
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    reducedMotion: 'no-preference',
  })
  const page = await context.newPage()

  // CSS 侧的动画同样放慢到 1/K（JS 侧由 TIME_SCALE 处理），两边同倍率
  const cdp = await context.newCDPSession(page)
  await cdp.send('Animation.enable')
  await cdp.send('Animation.setPlaybackRate', { playbackRate: 1 / TIME_K })

  // 时间缩放必须在页面脚本之前注入：把页面的 Date / performance.now /
  // 计时器整体除以 K。配合下面 CDP 的 Animation.setPlaybackRate(1/K)，
  // 页面等于在跑真正的慢动作——帧与帧之间是连续的真实状态，页面自己的
  // 动画（切页层叠、文件列表收放、阶段点脉冲、CTA 描边）都被原样录进来。
  await page.addInitScript({ content: `(${TIME_SCALE.toString()})(${TIME_K})` })

  // ── 不拦截任何请求 ────────────────────────────────────────────────────
  //
  // 这里曾经挂过一个假后端（page.route 拦截 /api/v1/**，按剧本分步放行
  // 任务阶段），理由是"示例数据模式一次轮询就到终态、文件列表会空"。
  // 那个理由不成立：示例数据模式的文件列表是有内容的（三份文件、状态正常），
  // 而阶段推进确实缺失——但缺的原因在 mock 层，已经在前端补上了
  // （见 src/api/index.js 的 mockSnapshot：按任务创建后经过的时长给出
  // 中间态，只用契约里已有的 PROCESSING / UPLOADED / PARSING）。
  //
  // 现在脚本不模拟应用，只模拟人：移动光标、点击、拖拽、滚动。
  // 所有页面动画都由前端自己播，脚本一个字节都不改。

  const errors = []
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(`console: ${m.text().slice(0, 200)}`)
  })

  const boxes = {}
  const stage = createStage(page, boxes, SEL, sampleFiles, cdp)

  try {
    // 首页的入场动画只在加载时播一次，所以导航放在第一幕的 prepare 里
    // （见 timeline.mjs）——这里只把地址交给舞台。
    // 示例数据模式：任务阶段由 mock 层按经过时长推进（见 src/api/index.js），
    // 所以页面会自己播完「排队中 → 解析文件中 → 交叉比对中 → 已生成结果」
    log(`  首页地址 ${baseUrl}/?mock=1#/（导航交由第一幕，入场动画落在第一幕）`)
    stage.homeUrl = `${baseUrl}/?mock=1#/`

    const result = await renderFrames({
      page,
      stage,
      framesDir: FRAMES_DIR,
      startFrom: START_FROM,
      fps: FPS_ARG,
      k: TIME_K,
    })

    if (argv.preview) {
      log(`\n  ✓ 预览模式：帧已渲染到 ${FRAMES_DIR}（未合成）`)
      log(`    ${result.totalFrames} 帧`)
    } else {
      const bytes = encode(FRAMES_DIR, OUT_FILE, FPS_ARG, ffmpeg)
      log(`  ✓ 视频：${OUT_FILE}（${(bytes / 1024 / 1024).toFixed(2)} MB）`)

      const poster = makePoster(FRAMES_DIR, POSTER_FILE, POSTER_MS, FPS_ARG, ffmpeg)
      log(`  ✓ 封面：${POSTER_FILE}（${(poster.size / 1024).toFixed(0)} KB，取自 ${(POSTER_MS / 1000).toFixed(1)}s）`)

    }

    // 中间帧与样例单证都放临时目录，结束清理；--keep-frames 可保留供排查
    if (!argv['keep-frames'] && !argv.preview && START_FROM === 0) {
      rmSync(WORK_DIR, { recursive: true, force: true, maxRetries: 3 })
    }

    if (errors.length) {
      log(`\n  ⚠ 页面报错 ${errors.length} 条（前 6 条）：`)
      for (const e of errors.slice(0, 6)) log(`    ${e}`)
    } else {
      log('  ✓ 页面无控制台报错')
    }

    log(`\n  总时长 ${(TOTAL_MS / 1000).toFixed(1)}s；分幕：`)
    SCENES.forEach((s, i) => {
      log(
        `    ${String(i + 1).padStart(2)}. ${s.label.padEnd(6, '　')} ` +
          `${(SCENE_STARTS[i] / 1000).toFixed(1)}s → ${((SCENE_STARTS[i] + s.durationMs) / 1000).toFixed(1)}s`
      )
    })
    log('')
  } finally {
    await browser.close()
    if (server) await server.stop()
  }
}

main()
  .then(() => {
    process.exitCode = EXIT.OK
  })
  .catch((err) => {
    if (err instanceof PreflightError) {
      fail(err.message, err.hint)
      process.exitCode = EXIT.ENV
      return
    }
    process.stderr.write(`\n✗ 录制失败：${err?.stack ?? err}\n\n`)
    process.exitCode = EXIT.RECORD
  })
