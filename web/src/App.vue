<script setup>
import { ref, computed, provide, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { isMock, listMockScenarios, setMockScenario, getEvaluation } from './api/index.js'
import { setMock } from './api/config.js'
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

/**
 * 数据源：mock 示例数据 / 真实后端。初始值在 config.js 里按
 * URL 参数 ?mock= → localStorage → 默认 mock 的顺序解析。
 * 顶栏切换后整页刷新：任务、缓存、错误提示都属于旧数据源，不值得就地迁移。
 */
const mock = ref(isMock())

function onSourceChange(event) {
  const next = event.target.value === 'mock'
  if (next === mock.value) return
  setMock(next)
  window.location.reload()
}

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
 * 上传页表单状态提升到 App 层：文件列表/目的国/备注在切页返回时保留，
 * 与任务状态（task）的生命周期一致——任务还在、输入却丢了，层级不一致。
 * scanWarnings 由文件内容异步检测得出，一并在 App 层持有，
 * 否则返回上传页时文件还在、扫描件警告却丢了。
 */
const uploadFiles = ref([])
const uploadCountry = ref('DE')
const uploadNotes = ref('')
const uploadScanWarnings = ref(new Set())
provide('uploadFiles', uploadFiles)
provide('uploadCountry', uploadCountry)
provide('uploadNotes', uploadNotes)
provide('uploadScanWarnings', uploadScanWarnings)

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
 * 用户上传的 File 对象映射，key 为 file.name，value 为 File。
 * File 对象只在浏览器内存里；上传页提交时写入，差异页「查看原文」用它拼 objectURL。
 * mock 场景不经过真实上传，映射为空，「查看原文」按钮随之不渲染（降级，不伪造）。
 * 写入（提交/清空）必然早于结果渲染，按钮显隐在渲染时按 key 现查，
 * 不需要逐个 key 的响应式追踪，普通 Map 即可。
 */
const sourceFiles = new Map()
provide('sourceFiles', {
  get: (name) => sourceFiles.get(name) ?? null,
  /** 整批替换：每次提交新检查时以当前选择的文件为准 */
  setAll: (files) => {
    sourceFiles.clear()
    for (const f of files ?? []) sourceFiles.set(f.name, f)
  },
  clear: () => sourceFiles.clear(),
})

/**
 * 评测数据缓存提升到 App 层：
 * 切页时 EvalPage 会卸载重挂载，缓存留在 provide 里，
 * 重挂载时直接复用，不再每次切页都重新请求一次。
 */
const evaluation = ref(null)
const evaluationLoaded = ref(false)
provide('evaluation', evaluation)
provide('evaluationLoaded', evaluationLoaded)

/**
 * 评测数据静默预取：App 挂载时就发起请求，用户切到评测页时缓存已就绪，
 * 不再出现骨架屏 → 内容的二次替换闪烁。不阻塞渲染；失败静默——
 * evaluationLoaded 保持 false，EvalPage 进入时会自行请求并展示错误态。
 */
onMounted(async () => {
  try {
    evaluation.value = await getEvaluation()
    evaluationLoaded.value = true
  } catch {
    /* 静默：错误态由 EvalPage 自己处理 */
  }
})

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

      <div class="mock-tools">
        <span
          v-if="mock"
          class="mock-flag"
          title="前端正在使用本地示例数据，未连接后端"
        >示例数据</span>
        <span
          v-else
          class="backend-flag"
          title="前端直连后端接口，所见均为真实处理结果"
        >真实后端</span>
        <select
          v-if="mock"
          v-model="mockScenario"
          class="mock-scenario-select"
          title="选择示例场景，下次提交检查时生效"
          @change="onScenarioChange"
        >
          <option v-for="key in mockScenarios" :key="key" :value="key">
            {{ SCENARIO_NAMES[key] ?? key }}
          </option>
        </select>
        <select
          :value="mock ? 'mock' : 'backend'"
          class="mock-scenario-select"
          title="切换数据来源，切换后页面自动刷新"
          @change="onSourceChange"
        >
          <option value="mock">示例数据</option>
          <option value="backend">真实后端</option>
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
