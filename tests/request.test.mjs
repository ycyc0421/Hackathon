/**
 * 请求生命周期：取消传播、单请求截止、重试边界、轮询软提示/硬截止。
 * 用可控 fetch 替身与注入时钟，不依赖真实网络与真实等待。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ApiError, requestOnce, request, pollTask, REQUEST_TIMEOUT_MS } from '../web/src/api/request.js'

/** 模拟浏览器 fetch：挂起直到调用方 signal 触发 abort 后拒绝 */
function hangingFetch() {
  return (_url, options) =>
    new Promise((_, reject) => {
      options?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    })
}

async function kindOf(promise) {
  try {
    await promise
    return null
  } catch (e) {
    assert.ok(e instanceof ApiError, `应为 ApiError，实为 ${e}`)
    return e.kind
  }
}

// —— 以下测试通过临时替换 globalThis.fetch 注入替身 ——

async function withFetch(fetchImpl, fn) {
  const original = globalThis.fetch
  globalThis.fetch = fetchImpl
  try {
    return await fn()
  } finally {
    globalThis.fetch = original
  }
}

test('abort 传播到 fetch：signal 真正进入请求，Promise 以 CANCELED 结束', async () => {
  await withFetch(hangingFetch(), async () => {
    let observedSignal = null
    globalThis.fetch = (url, options) => {
      observedSignal = options?.signal ?? null
      return hangingFetch()(url, options)
    }
    const ctrl = new AbortController()
    const p = requestOnce('/x', {}, { signal: ctrl.signal, timeoutMs: 60_000 })
    setTimeout(() => ctrl.abort(), 5)
    assert.equal(await kindOf(p), 'CANCELED')
    assert.ok(observedSignal, 'signal 必须传入 fetch')
  })
})

test('fetch 永不响应：按应用层截止以 TIMEOUT 结束', async () => {
  await withFetch(hangingFetch(), async () => {
    assert.equal(await kindOf(requestOnce('/x', {}, { timeoutMs: 20 })), 'TIMEOUT')
  })
})

test('响应体长期读不完：同样按截止结束', async () => {
  // 模拟浏览器行为：读体阶段连接被 abort 时 json() 也会拒绝
  await withFetch(
    async (_url, options) => ({
      ok: true,
      json: () =>
        new Promise((_, reject) => {
          options?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        }),
    }),
    async () => {
      assert.equal(await kindOf(requestOnce('/x', {}, { timeoutMs: 20 })), 'TIMEOUT')
    }
  )
})

test('CANCELED / TIMEOUT 不进入重试', async () => {
  await withFetch(hangingFetch(), async () => {
    let calls = 0
    globalThis.fetch = (...args) => {
      calls += 1
      return hangingFetch()(...args)
    }
    assert.equal(await kindOf(request('/x', {}, { timeoutMs: 15, retries: 3, baseDelayMs: 1 })), 'TIMEOUT')
    assert.equal(calls, 1)
  })
})

test('4xx 不重试，网络错误重试到上限', async () => {
  await withFetch(async () => ({ ok: false, status: 400, json: async () => ({ error: { message: 'bad', code: 'BAD' } }) }), async () => {
    let calls = 0
    const orig = globalThis.fetch
    globalThis.fetch = (...a) => { calls += 1; return orig(...a) }
    assert.equal(await kindOf(request('/x', {}, { retries: 3, baseDelayMs: 1 })), 'SERVER')
    assert.equal(calls, 1)
  })

  await withFetch(async () => { throw new TypeError('fetch failed') }, async () => {
    let calls = 0
    const orig = globalThis.fetch
    globalThis.fetch = (...a) => { calls += 1; return orig(...a) }
    assert.equal(await kindOf(request('/x', {}, { retries: 3, baseDelayMs: 1 })), 'NETWORK')
    assert.equal(calls, 3)
  })
})

test('正常成功不被残留定时器误判为超时', async () => {
  await withFetch(async () => ({ ok: true, json: async () => ({ hello: 1 }) }), async () => {
    const body = await requestOnce('/x', {}, { timeoutMs: 50 })
    assert.deepEqual(body, { hello: 1 })
    // 等过截止时长，确认没有迟到的 reject / unhandled
    await new Promise((r) => setTimeout(r, 70))
  })
})

// —— 轮询：软提示必须先于硬截止可见（虚拟时钟） ——

function virtualClock() {
  let t = 0
  return {
    now: () => t,
    sleep: (ms) => { t += ms; return Promise.resolve() },
  }
}

test('持续 PROCESSING：慢提示在软提示线触发，硬截止抛 TIMEOUT', async () => {
  const clock = virtualClock()
  let slowCalls = 0
  let ticks = 0
  const kind = await kindOf(
    pollTask(async () => ({ status: 'PROCESSING' }), {
      onTick: () => { ticks += 1 },
      onSlow: () => { slowCalls += 1 },
      intervalMs: 1500,
      maxAttempts: 60, // 用较短窗口验证截止行为
      slowMs: 30_000, // 30 秒软提示线，与产品配置一致
      now: clock.now,
      sleep: clock.sleep,
    })
  )
  assert.equal(kind, 'TIMEOUT')
  assert.equal(ticks, 60)
  assert.equal(slowCalls, 1, '软提示必须先于硬截止触发一次')
  assert.equal(clock.now(), 60 * 1500)
})

test('CPU 模型处理超过 90 秒后仍可取得终态', async () => {
  const clock = virtualClock()
  let calls = 0
  const task = await pollTask(async () => ({ status: ++calls === 250 ? 'COMPLETED' : 'PROCESSING' }), {
    intervalMs: 1500, maxAttempts: 1200, slowMs: 30_000,
    now: clock.now, sleep: clock.sleep,
  })
  assert.equal(task.status, 'COMPLETED')
  assert.ok(clock.now() > 90_000)
})

test('慢提示不会在到达软提示线之前触发', async () => {
  const clock = virtualClock()
  const slowAt = []
  await kindOf(
    pollTask(async () => ({ status: 'PROCESSING' }), {
      onSlow: () => slowAt.push(clock.now()),
      intervalMs: 1500,
      maxAttempts: 5,
      slowMs: 30_000,
      now: clock.now,
      sleep: clock.sleep,
    })
  )
  assert.deepEqual(slowAt, [], '5 次轮询（7.5s）远未到 30s，不应触发慢提示')
})

test('拿到终态立即返回，不再等待也不超时', async () => {
  const clock = virtualClock()
  let ticks = 0
  const task = await pollTask(
    async () => (++ticks === 3 ? { status: 'COMPLETED' } : { status: 'PROCESSING' }),
    { intervalMs: 1500, maxAttempts: 60, slowMs: 30_000, now: clock.now, sleep: clock.sleep }
  )
  assert.equal(task.status, 'COMPLETED')
  assert.equal(ticks, 3)
})

test('轮询中 abort：CANCELED 结束', async () => {
  const clock = virtualClock()
  const ctrl = new AbortController()
  let ticks = 0
  const kind = await kindOf(
    pollTask(
      async () => {
        ticks += 1
        if (ticks === 2) ctrl.abort()
        return { status: 'PROCESSING' }
      },
      { signal: ctrl.signal, intervalMs: 1500, maxAttempts: 60, slowMs: 30_000, now: clock.now, sleep: clock.sleep }
    )
  )
  assert.equal(kind, 'CANCELED')
})

test('单请求默认截止为 30 秒', () => {
  assert.equal(REQUEST_TIMEOUT_MS, 30_000)
})
