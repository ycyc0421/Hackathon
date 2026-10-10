<script setup>
import { ref, computed, provide, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { USE_MOCK, listMockScenarios, setMockScenario } from './api/index.js'
import ErrorBoundary from './components/ErrorBoundary.vue'
import UploadPage from './pages/UploadPage.vue'
import DiffPage from './pages/DiffPage.vue'
import ReportPage from './pages/ReportPage.vue'
import EvalPage from './pages/EvalPage.vue'

const PAGES = [
  { key: 'upload', label: '上传', component: UploadPage },
  { key: 'diff', label: '差异', component: DiffPage },
  { key: 'report', label: '报告', component: ReportPage },
  { key: 'eval', label: '评测', component: EvalPage },
]

const active = ref('upload')

/** mock 场景选择。key → 中文名只用于展示，场景数据以 api 层注册表为准 */
const SCENARIO_NAMES = {
  'single-item': '单品名 · 有冲突',
  'partial-fail': '单品名 · 部分失败',
  'multi-item': '双品名 · 分组',
  clean: '全部一致',
}
const mockScenarios = listMockScenarios()
const mockScenario = ref('single-item')

function onScenarioChange() {
  setMockScenario(mockScenario.value)
}

/** 当前检查任务。由上传页写入，差异页和报告页读取 */
const task = ref(null)
const taskError = ref(null)
const isRunning = ref(false)

provide('task', task)
provide('taskError', taskError)
provide('isRunning', isRunning)

/**
 * 跨页导航：报告页的条目可以直接跳到差异页对应位置。
 * anchor 经 pendingAnchor 传给目标页（页面随切页重挂载，挂载时消费并清空）。
 */
const pendingAnchor = ref(null)

function go(page, anchor) {
  pendingAnchor.value = anchor ?? null
  active.value = page
}

provide('pendingAnchor', pendingAnchor)
provide('navigate', { go })

/**
 * 评测数据缓存提升到 App 层：
 * 切页时 EvalPage 会卸载重挂载，缓存留在 provide 里，
 * 重挂载时直接复用，不再每次切页都重新请求一次。
 */
const evaluation = ref(null)
const evaluationLoaded = ref(false)
provide('evaluation', evaluation)
provide('evaluationLoaded', evaluationLoaded)

/** 差异页有问题可看时才点亮，给用户一个"该去哪看"的提示 */
const problemCount = computed(() => {
  if (!task.value) return 0
  return task.value.comparisons?.filter((c) => c.status !== 'MATCH' && c.status !== 'SINGLE_SOURCE').length ?? 0
})

const current = computed(() => PAGES.find((p) => p.key === active.value)?.component)

/** 没有任务时，差异页和报告页没有内容可显示 */
function isLocked(key) {
  return (key === 'diff' || key === 'report') && !task.value
}

/** 下划线指示条：按当前标签的实测位置与宽度移动，跟随窗口尺寸变化 */
const tabsRef = ref(null)
const indicatorStyle = ref({ opacity: '0' })

async function updateIndicator() {
  await nextTick()
  const root = tabsRef.value
  const el = root?.querySelector('.tab.active')
  if (!root || !el) {
    indicatorStyle.value = { opacity: '0' }
    return
  }
  indicatorStyle.value = {
    width: `${el.offsetWidth}px`,
    transform: `translateX(${el.offsetLeft}px)`,
    opacity: '1',
  }
}

let resizeObserver = null
onMounted(() => {
  updateIndicator()
  if (tabsRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(updateIndicator)
    resizeObserver.observe(tabsRef.value)
  }
  window.addEventListener('resize', updateIndicator)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  window.removeEventListener('resize', updateIndicator)
})

watch(active, updateIndicator)
</script>

<template>
  <ErrorBoundary>
    <div class="app">
      <header class="topbar">
      <div class="brand">
        <span class="brand-mark">单证校验</span>
        <span class="brand-sub">跨境物流 · 交叉比对与合规提示</span>
      </div>

      <nav ref="tabsRef" class="tabs">
        <button
          v-for="p in PAGES"
          :key="p.key"
          class="tab"
          :class="{ active: active === p.key, locked: isLocked(p.key) }"
          :disabled="isLocked(p.key)"
          :title="isLocked(p.key) ? '先在上传页创建一次检查' : ''"
          @click="active = p.key"
        >
          {{ p.label }}
          <span v-if="p.key === 'diff' && problemCount" class="tab-badge">{{ problemCount }}</span>
        </button>
        <span class="tab-indicator" :style="indicatorStyle" aria-hidden="true" />
      </nav>

      <div v-if="USE_MOCK" class="mock-tools">
        <span class="mock-flag" title="前端正在使用本地示例数据，未连接后端">示例数据</span>
        <select
          v-model="mockScenario"
          class="mock-scenario-select"
          title="选择示例场景，下次提交检查时生效"
          @change="onScenarioChange"
        >
          <option v-for="key in mockScenarios" :key="key" :value="key">
            {{ SCENARIO_NAMES[key] ?? key }}
          </option>
        </select>
      </div>
    </header>

    <main class="content">
      <Transition name="fade" mode="out-in">
        <component :is="current" :key="active" />
      </Transition>
    </main>

      <footer class="footer">
        <span>契约草案 v0.1 · 未冻结</span>
        <span v-if="task" class="task-ref">任务 {{ task.task_id }}</span>
      </footer>
    </div>
  </ErrorBoundary>
</template>
