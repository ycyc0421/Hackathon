/**
 * env.mjs — 录制环境：依赖解析、前置检查、静态服务器自管。
 *
 * 目标是**能进 CI 独立生成**：不依赖本机的绝对路径、不依赖"外面已经
 * 起好的 dev server"，任何一步失败都以非零码退出并给出可操作的提示。
 *
 * 路径解析顺序（每一处都先试标准位置，再退回本机路径）：
 *   playwright-core  →  import('playwright-core')  →  $PLAYWRIGHT_CORE_PATH
 *                       →  本机 video-gen 的 node_modules
 *   Chromium         →  交给 playwright 自己解析（不传 executablePath）
 *                       →  $CHROMIUM_PATH
 *                       →  本机 ~/.cache/ms-playwright 下的 chromium-*
 *   ffmpeg           →  $FFMPEG_PATH  →  PATH 里的 ffmpeg
 */

import { existsSync, readdirSync, statSync } from 'node:fs'
import { spawn, spawnSync } from 'node:child_process'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { createConnection } from 'node:net'

/** 退出码：区分"环境没装好"和"录制本身失败"，CI 里好定位 */
export const EXIT = {
  OK: 0,
  /** 前置依赖缺失（ffmpeg / playwright / 浏览器 / 构建产物） */
  ENV: 2,
  /** 录制过程中失败 */
  RECORD: 3,
}

export class PreflightError extends Error {
  constructor(message, hint) {
    super(message)
    this.name = 'PreflightError'
    this.hint = hint
  }
}

/** 统一的失败输出：原因 + 可操作的下一步 */
export function fail(message, hint) {
  process.stderr.write(`\n✗ ${message}\n`)
  if (hint) for (const line of String(hint).split('\n')) process.stderr.write(`  → ${line}\n`)
  process.stderr.write('\n')
}

/* ── playwright ────────────────────────────────────────────────────────── */

/** 按"先标准、后本机"的顺序拿到 playwright-core */
export async function loadPlaywright() {
  const tried = []
  const roots = [
    'playwright-core',
    process.env.PLAYWRIGHT_CORE_PATH,
    join(homedir(), 'projects/video-gen/node_modules/playwright-core'),
    join(homedir(), '.cache/demo-tools/node_modules/playwright-core'),
  ].filter(Boolean)
  // 每个位置都试「包名/目录」与「目录下的 index.mjs」：
  // 目录形式的动态 import 在 Node 里不会自动解析到 index.mjs
  const candidates = []
  for (const spec of roots) {
    candidates.push(spec)
    if (spec.startsWith('/') || spec.startsWith('.')) candidates.push(join(spec, 'index.mjs'))
  }

  for (const spec of candidates) {
    tried.push(spec)
    try {
      const mod = await import(spec)
      if (mod?.chromium) return { mod, from: spec }
    } catch {
      /* 试下一个 */
    }
  }
  throw new PreflightError(
    '找不到 playwright-core',
    '任选一种方式：\n' +
      '  1) 在运行目录安装：npm i -D playwright-core（本仓库的 web/ 不允许加依赖，\n' +
      '     请在 CI 步骤里单独装到别的目录，或直接用下面的环境变量指定）\n' +
      '  2) 用 PLAYWRIGHT_CORE_PATH 指向已安装的 playwright-core 目录\n' +
      '  3) 本机已装的话可指向 ~/projects/video-gen/node_modules/playwright-core\n' +
      `已尝试：${tried.join('、')}`
  )
}

/**
 * Chromium 可执行文件。
 * 优先让 playwright 自己解析（不传 executablePath），只有它找不到、
 * 或显式给了 CHROMIUM_PATH 时才返回具体路径。
 */
export function resolveChromiumPath() {
  if (process.env.CHROMIUM_PATH) {
    if (!existsSync(process.env.CHROMIUM_PATH)) {
      throw new PreflightError(
        `CHROMIUM_PATH 指向的文件不存在：${process.env.CHROMIUM_PATH}`,
        '确认路径，或去掉该环境变量让 playwright 自己找浏览器'
      )
    }
    return process.env.CHROMIUM_PATH
  }
  // 本机缓存里的 chromium-*（CI 上通常不存在，返回 null 交给 playwright）
  const cacheRoot = join(homedir(), '.cache/ms-playwright')
  if (existsSync(cacheRoot)) {
    const dirs = readdirSync(cacheRoot).filter((d) => d.startsWith('chromium-')).sort()
    for (const d of dirs.reverse()) {
      for (const rel of ['chrome-linux64/chrome', 'chrome-linux/chrome', 'chrome-mac/Chromium.app/Contents/MacOS/Chromium']) {
        const p = join(cacheRoot, d, rel)
        if (existsSync(p)) return p
      }
    }
  }
  return null
}

/** 浏览器起不来时给出的可操作提示 */
export function browserHint(err) {
  const msg = String(err?.message ?? err)
  if (/Executable doesn't exist|No such file|cannot find/i.test(msg)) {
    return (
      '浏览器未安装或路径不对。任选一种方式：\n' +
      '  1) 安装浏览器：npx playwright install chromium（或 --with-deps 装系统依赖）\n' +
      '  2) 用 CHROMIUM_PATH 指向已有的 Chromium/Chrome 可执行文件\n' +
      '  3) 本机可指向 ~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome'
    )
  }
  if (/sandbox/i.test(msg)) {
    return '沙箱受限：脚本已带 --no-sandbox，若仍失败请检查容器权限（需 SYS_ADMIN 或特权模式）'
  }
  return '检查 playwright 与浏览器的安装是否完整（npx playwright install chromium）'
}

/* ── ffmpeg ────────────────────────────────────────────────────────────── */

/** 拿到可用的 ffmpeg 可执行文件路径 */
export function resolveFfmpeg() {
  const candidates = [process.env.FFMPEG_PATH, 'ffmpeg'].filter(Boolean)
  for (const bin of candidates) {
    try {
      const r = spawnSync(bin, ['-hide_banner', '-version'], { stdio: 'ignore' })
      if (r.status === 0) return bin
    } catch {
      /* 试下一个 */
    }
  }
  throw new PreflightError(
    '找不到可用的 ffmpeg',
    '任选一种方式：\n' +
      '  1) 系统包管理器安装（Debian/Ubuntu：apt-get install -y ffmpeg）\n' +
      '  2) 用 FFMPEG_PATH 指向 ffmpeg 可执行文件\n' +
      '  3) CI 里可用 npx --yes ffmpeg-static 之类的方式提供'
  )
}

/* ── 静态服务器 ────────────────────────────────────────────────────────── */

/** 端口是否已被占用（用于判断服务器是否就绪） */
function portOpen(port, host = '127.0.0.1', timeoutMs = 400) {
  return new Promise((resolve) => {
    const socket = createConnection({ port, host })
    const done = (ok) => {
      socket.destroy()
      resolve(ok)
    }
    socket.setTimeout(timeoutMs)
    socket.once('connect', () => done(true))
    socket.once('timeout', () => done(false))
    socket.once('error', () => done(false))
  })
}

/** HTTP 是否已经能响应（比端口探测更可靠：端口通了不代表服务就绪） */
async function httpReady(url, timeoutMs = 1200) {
  try {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), timeoutMs)
    const res = await fetch(url, { signal: ctrl.signal })
    clearTimeout(timer)
    return res.ok || res.status === 404 // 404 也说明服务在响应
  } catch {
    return false
  }
}

/**
 * dist/ 是否比 src/ 旧。
 * vite preview 服务的正是 dist/，构建过期就会录出一版旧界面，
 * 而这种错误没有任何报错——必须显式检查。
 */
function distIsStale(webDir) {
  const indexHtml = join(webDir, 'dist/index.html')
  if (!existsSync(indexHtml)) return true
  const builtAt = statSync(indexHtml).mtimeMs
  const dirs = ['src', 'index.html', 'vite.config.js', 'package.json']
  const walk = (p) => {
    if (!existsSync(p)) return false
    const st = statSync(p)
    if (st.isFile()) return st.mtimeMs > builtAt
    for (const entry of readdirSync(p)) {
      if (walk(join(p, entry))) return true
    }
    return false
  }
  return dirs.some((d) => walk(join(webDir, d)))
}

/**
 * 自己把前端跑起来，录完自己关掉。
 *
 * 优先 `vite preview`（基于已构建的 dist/，更接近线上产物、也更稳）；
 * dist/ 不存在或比 src/ 旧时退回 `vite dev`——过期构建会静默录出旧界面，
 * 比慢一点危险得多。两者都在 try/finally 与进程信号里收尾，不留孤儿进程。
 *
 * @returns {{ url: string, stop: () => Promise<void> } | null}
 *          --base-url 已给定时返回 null（不需要自管服务器）
 */
export async function startServer({ webDir, port = 4173, prefer = 'preview', log = () => {} }) {
  const distDir = join(webDir, 'dist')
  const hasDist = existsSync(join(distDir, 'index.html'))
  let usePreview = prefer === 'preview' && hasDist
  if (usePreview && distIsStale(webDir)) {
    log('  dist/ 比 src/ 旧，改用 vite dev（过期构建会录出旧界面）')
    usePreview = false
  }
  if (prefer === 'preview' && !hasDist) {
    log('  没有 dist/，改用 vite dev（想用 preview 请先 npm run build）')
  }
  const args = usePreview
    ? ['vite', 'preview', '--port', String(port), '--strictPort']
    : ['vite', '--port', String(port), '--strictPort']
  const url = `http://localhost:${port}`
  const label = usePreview ? 'vite preview（dist/）' : 'vite dev'

  if (await httpReady(url)) {
    log(`  ${url} 已有服务在跑，直接使用`)
    return { url, stop: async () => {}, reused: true }
  }

  log(`  启动 ${label} → ${url}`)
  const child = spawn('npx', args, {
    cwd: webDir,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: process.env,
    detached: false,
  })
  let output = ''
  child.stdout.on('data', (d) => {
    output += d.toString()
  })
  child.stderr.on('data', (d) => {
    output += d.toString()
  })
  let exited = null
  child.once('exit', (code) => {
    exited = code
  })

  const deadline = Date.now() + 60_000
  while (Date.now() < deadline) {
    if (exited !== null) {
      throw new PreflightError(
        `${label} 启动即退出（code ${exited}）`,
        `输出：\n${output.trim().split('\n').slice(-12).join('\n')}`
      )
    }
    if (await httpReady(url)) break
    await new Promise((r) => setTimeout(r, 400))
  }
  if (!(await httpReady(url))) {
    child.kill('SIGTERM')
    throw new PreflightError(
      `${label} 在 60 秒内没有就绪`,
      `输出：\n${output.trim().split('\n').slice(-12).join('\n')}`
    )
  }
  log(`  ${label} 就绪`)

  const stop = async () => {
    if (child.exitCode !== null || child.signalCode) return
    child.kill('SIGTERM')
    const t = Date.now()
    while (child.exitCode === null && Date.now() - t < 5000) {
      await new Promise((r) => setTimeout(r, 100))
    }
    if (child.exitCode === null) child.kill('SIGKILL')
  }
  return { url, stop, reused: false }
}

/**
 * 注册进程级清理：异常退出、Ctrl-C、CI 取消都要把子进程带走，
 * 否则 CI 会因为残留进程挂住。
 */
export function registerCleanup(cleanups) {
  let done = false
  const run = async (code) => {
    if (done) return
    done = true
    for (const fn of cleanups) {
      try {
        await fn()
      } catch {
        /* 清理失败不覆盖原始错误 */
      }
    }
    if (code !== undefined) process.exit(code)
  }
  for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(sig, () => {
      process.stderr.write(`\n收到 ${sig}，清理中…\n`)
      run(130)
    })
  }
  return () => run()
}

/** 端口是否可用（给 --port 自动挑端口用） */
export const isPortOpen = portOpen
