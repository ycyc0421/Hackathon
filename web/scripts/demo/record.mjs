/**
 * record.mjs — 逐帧录制主循环。
 *
 * 流程：按时间线逐帧渲染 → 每帧一次截图（JPEG，运镜即裁切）→ ffmpeg 合成 → 抽封面。
 *
 * 三条关键实现决定：
 *
 * 1) 逐帧截图，不录屏。录屏（CDP screencast）拿不到确定帧率，也无法按
 *    视频时间驱动镜头；逐帧截图时每帧的镜头、滚动、光标、遮罩都是算出来的，
 *    任意一帧都可复现，渲染慢也不会让画面与剧本错位。
 *
 * 2) 运镜 = 截图裁切。每帧只截 1280/zoom 那么大的一块再放大回 1280×800。
 *    所以截图必须按 1.5 倍设备像素比拍，否则推近后的画面会被放大到糊。
 *
 * 3) 帧序列尺寸恒定。裁切框长宽比恒等于视口、缩放时同比例变化，因此每帧
 *    缩放后都是 1280×800，ffmpeg 只需一次 scale。实测 ffmpeg 对尺寸变化的
 *    帧序列会取第一帧尺寸并静默拉伸，必须避开。
 *
 * 页面自身的动画**全部保留**。逐帧截图能录到它们，靠的是把整个页面的
 * 时间放慢 K 倍（默认 4）：
 *   - CDP 的 Animation.setPlaybackRate(1/K) 放慢 CSS transition / animation；
 *   - 注入脚本把 Date.now / performance.now / setTimeout / setInterval 一起
 *     除以 K（见 overlays.mjs 的 TIME_SCALE），让 JS 侧的补间与 CSS 同步；
 *   - 两者同倍率，页面等于在跑真正的慢动作，帧与帧之间是连续的真实状态。
 *
 * 于是"切页的纸张层叠""文件列表的收放""阶段点脉冲"这些用户真正会看到
 * 的动效，都被原样录进去，而不是在脚本里重写一遍。放慢 4 倍后，
 * 页面 300ms 的切页过渡有 1.2s 墙钟时间，60fps 下能采到十几帧。
 *
 * 剧本只负责两件事：像人一样操作、决定镜头看哪里。
 */

import { mkdirSync, rmSync, existsSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { execFileSync } from 'node:child_process'
import { OUT_W, OUT_H } from './camera.mjs'
import { APPLY_FRAME } from './overlays.mjs'
import { SCENES, SCENE_STARTS, TOTAL_MS, FPS, POSTER_MS, sampleScene } from './timeline.mjs'

/** 截图设备像素比：推近后画面不被放大糊掉的前提 */
const DPR = 1.5

/** 动作级追踪（DEMO_TRACE=1），排查"动作执行了但页面没反应" */
const TRACE = process.env.DEMO_TRACE === '1'

/** 渲染一帧并落盘。尺寸取整后必须 ≥1px，否则 Playwright 直接报错 */
async function shoot(page, clip, path) {
  await page.screenshot({
    path,
    type: 'jpeg',
    quality: 92,
    clip: {
      x: Math.round(clip.x),
      y: Math.round(clip.y),
      width: Math.max(2, Math.round(clip.w)),
      height: Math.max(2, Math.round(clip.h)),
    },
    // 关键：绝不能传 animations:'disabled'——那会把页面动画直接快进到
    // 终态，等于把前端动效抹掉。这里要让动画照常播，录到的才是真实效果。
    animations: 'allow',
    caret: 'hide',
  })
}

/**
 * 逐帧渲染。
 *
 * 【关键：按页面时钟取帧】页面时间被放慢 K 倍（见 overlays.mjs 的
 * TIME_SCALE）。要让页面自己的动画在成片里保持**原本的速度**，就必须
 * 让"一帧 = 1/fps 秒的页面时间"：
 *
 *   - 放慢 K 倍是为了给截图留出墙钟时间（截图约 50ms，而 1/60s 只有
 *     16.7ms，不放慢根本采不到连续状态）；
 *   - 每帧等页面时钟走到 t 才拍，保证动画不被拖成慢动作。
 *
 * 节拍必须锚在**页面自己的时钟**上，不能锚在墙钟上：点击等动作本身会
 * 消耗页面时间（mouse.down/up、等稳定都要花墙钟），按墙钟排程会在动作
 * 之后"追赶"，把动画中间的帧整段丢掉（实测：切页过渡只剩两三帧）。
 * 锚在页面时钟上则动作花掉多少页面时间就顺延多少，动画一帧不漏。
 *
 * @param {{ page, stage, framesDir, startFrom?, fps?, k?, onFrame? }} options
 */
export async function renderFrames({ page, stage, framesDir, startFrom = 0, fps = FPS, k = 4, onFrame }) {
  const frameMs = 1000 / fps
  if (existsSync(framesDir)) rmSync(framesDir, { recursive: true, force: true, maxRetries: 5 })
  mkdirSync(framesDir, { recursive: true })

  const startedAt = SCENE_STARTS[startFrom] ?? 0
  const totalMs = TOTAL_MS - startedAt
  const totalFrames = Math.ceil(totalMs / frameMs)
  const base = Math.round(startedAt / frameMs)

  console.log(
    `  共 ${SCENES.length} 幕 / ${(TOTAL_MS / 1000).toFixed(1)}s；` +
      `从第 ${startFrom + 1} 幕起渲染 ${totalFrames} 帧（${fps}fps，${(totalMs / 1000).toFixed(1)}s）`
  )

  let frame = 0
  /** 已执行的动作（`幕:序号`）。跨幕不复用，只用来保证每个动作只跑一次 */
  const fired = new Set()
  let lateFrames = 0

  /** 读页面当前时钟（已被 TIME_SCALE 放慢） */
  const pageClock = () => page.evaluate(() => Date.now())

  /**
   * 等到页面时钟到达 target 再继续。
   * 页面时钟按 墙钟/K 前进，所以需要睡 (target - now) * K 的墙钟。
   * 超过一帧的落后才计入掉帧统计（单帧微小超时是正常的）。
   */
  const waitForClock = async (target) => {
    const now = await pageClock()
    const needVirtual = target - now
    if (needVirtual > 0) {
      await new Promise((r) => setTimeout(r, needVirtual * k))
    } else if (needVirtual < -frameMs) {
      lateFrames += 1
    }
  }
  for (let si = startFrom; si < SCENES.length; si += 1) {
    const scene = SCENES[si]
    const sceneStart = SCENE_STARTS[si]
    console.log(`  ▸ 幕 ${si + 1}/${SCENES.length} ${scene.label}（${(scene.durationMs / 1000).toFixed(1)}s）`)

    if (scene.prepare) await scene.prepare(stage)
    await stage.refresh()
    // 本幕第一帧的页面时钟锚点：prepare 之后才取，准备动作的耗时不算进本幕
    const sceneClock0 = await pageClock()

    const frames = Math.round(scene.durationMs / frameMs)
    for (let i = 0; i < frames; i += 1) {
      const t = i * frameMs
      stage.now = sceneStart + t

      // 等页面时钟走到本帧对应的时刻再拍，动画即按原速入镜
      await waitForClock(sceneClock0 + t)

      // 定点动作：以"跨过时刻"为触发条件（t 单调递增），每个动作只跑一次。
      // 不用 [at, at+frameMs) 这种窗口判断——帧间隔与 at 的浮点误差会让窗口
      // 边界上的动作一次都不触发或多触发一次，这是实测踩过的坑。
      for (let ai = 0; ai < (scene.actions ?? []).length; ai += 1) {
        const action = scene.actions[ai]
        const key = `${si}:${ai}`
        if (fired.has(key) || t < action.at) continue
        fired.add(key)
        if (TRACE) {
          const snap = await page.evaluate(() => ({
            files: document.querySelectorAll('.file-item').length,
            submitDisabled: document.querySelector('.actions .btn.primary')?.disabled ?? null,
            status: !!document.querySelector('.status-row'),
          }))
          console.log(
            `    [trace] 幕${si} 动作${ai}(at=${action.at}) t=${Math.round(t)} ` +
              `video=${((sceneStart + t) / 1000).toFixed(2)}s ${JSON.stringify(snap)}`
          )
        }
        try {
          await action.run(stage)
        } catch (err) {
          process.stderr.write(
            `    [warn] 动作失败 @${((sceneStart + t) / 1000).toFixed(2)}s：${err.message}\n`
          )
        }
        // 动作后只重新测量坐标，不等稳定：等稳定会把页面刚触发的过渡
        // 整段消耗掉，成片里就只剩硬切（"没有复用页面切页动画"的根因）。
        // 需要等稳定的动作，自己在 run 里显式 await。
        await stage.refresh()
      }

      const state = sampleScene(scene, t, stage)
      await page.evaluate(APPLY_FRAME(state))

      const index = base + frame
      const path = join(framesDir, `f-${String(index).padStart(6, '0')}.jpg`)
      await shoot(page, state.clip, path)
      if (onFrame) await onFrame({ index, videoMs: sceneStart + t, state, path })
      frame += 1

      if (frame % (fps * 4) === 0) {
        process.stdout.write(`    ${((frame * frameMs) / 1000).toFixed(0)}s / ${(totalMs / 1000).toFixed(0)}s\n`)
      }
    }

    // 自检：本幕声明的动作若有没跑到的，明确报出来（静默漏跑比报错更难查）
    const missed = (scene.actions ?? [])
      .map((a, ai) => ({ a, ai }))
      .filter(({ ai }) => !fired.has(`${si}:${ai}`))
    if (missed.length) {
      process.stderr.write(
        `    [warn] 幕「${scene.label}」有 ${missed.length} 个动作未执行：` +
          missed.map(({ a, ai }) => `${ai}(at=${a.at})`).join('、') +
          '\n'
      )
    }
  }
  return { frames: base + frame, totalFrames: base + frame, totalMs }
}

/** ffmpeg 合成：恒定尺寸帧序列 → H.264 */
export function encode(framesDir, outFile, fps = FPS, ffmpeg = 'ffmpeg') {
  mkdirSync(dirname(outFile), { recursive: true })
  console.log(`  合成 ${outFile}`)
  execFileSync(
    ffmpeg,
    [
      '-y', '-hide_banner', '-loglevel', 'error', '-stats',
      '-framerate', String(fps),
      '-i', join(framesDir, 'f-%06d.jpg'),
      '-vf', `scale=${OUT_W}:${OUT_H}:flags=lanczos,format=yuv420p`,
      '-c:v', 'libx264',
      '-preset', 'slow',
      '-crf', '18',
      '-g', String(fps * 2),
      '-movflags', '+faststart',
      outFile,
    ],
    { stdio: ['ignore', 'inherit', 'inherit'] }
  )
  return statSync(outFile).size
}

/** 从帧序列里挑一帧做封面 */
export function makePoster(framesDir, posterFile, posterMs, fps = FPS, ffmpeg = 'ffmpeg') {
  const index = Math.round(posterMs / (1000 / fps))
  const src = join(framesDir, `f-${String(index).padStart(6, '0')}.jpg`)
  if (!existsSync(src)) throw new Error(`封面帧不存在：${src}`)
  mkdirSync(dirname(posterFile), { recursive: true })
  execFileSync(
    ffmpeg,
    [
      '-y', '-hide_banner', '-loglevel', 'error',
      '-i', src,
      // 截图是 1.5 倍设备像素（1920×1200），缩到与视频同尺寸，观感一致
      '-vf', `scale=${OUT_W}:${OUT_H}:flags=lanczos`,
      '-q:v', '3',
      posterFile,
    ],
    { stdio: 'inherit' }
  )
  return { src, size: statSync(posterFile).size }
}

export { POSTER_MS, OUT_W, OUT_H, DPR }
