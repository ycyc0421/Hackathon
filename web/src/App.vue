<script setup>
import { ref, computed, provide, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { isMock, listMockScenarios, setMockScenario, getEvaluation } from './api/index.js'
import { setMock } from './api/config.js'
import { needsReview } from './utils/needsReview.js'
import ErrorBoundary from './components/ErrorBoundary.vue'
import AppSelect from './components/AppSelect.vue'
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

const SOURCE_OPTIONS = [
  { value: 'mock', label: '示例数据' },
  { value: 'backend', label: '真实后端' },
]

function onSourceChange(value) {
  const next = value === 'mock'
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
const mockScenario = ref('single-item')
const scenarioOptions = listMockScenarios().map((key) => ({
  value: key,
  label: SCENARIO_NAMES[key] ?? key,
}))

function onScenarioChange() {
  setMockScenario(mockScenario.value)
}

/**
 * 移动端（≤640px）mock 工具收进徽标弹层：顶栏只留数据源徽标，
 * 点徽标在其下方弹出小面板，面板内放场景/来源两个下拉。
 * 桌面端徽标只是标识，点击不响应；弹层开/关走 CSS 透明度过渡。
 */
const mockPanelOpen = ref(false)

function toggleMockPanel() {
  if (!window.matchMedia('(max-width: 640px)').matches) return
  mockPanelOpen.value = !mockPanelOpen.value
}

/** 点面板外任意处收起 */
function onDocumentClick(e) {
  if (!mockPanelOpen.value) return
  if (e.target.closest?.('.mock-tools')) return
  mockPanelOpen.value = false
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
/** 本次切页是否锚点跳转：是则滚动交给目标页挂载时的锚点定位，进场钩子不碰滚动 */
let anchorJump = false

function go(page, anchor) {
  pendingAnchor.value = anchor ?? null
  anchorJump = !!anchor
  active.value = page
}

provide('pendingAnchor', pendingAnchor)
provide('navigate', { go })

/**
 * 差异页跨页状态提升到 App 层：筛选与每张卡片的 表格/对照 选择
 * 在切页返回时保留——页面内容（task）还在，查看进度却丢了，层级不一致。
 * 与 uploadFiles 同一模式；views 保持 new Map 整体赋值的响应式写法。
 */
const diffFilter = ref('problems')
const diffViews = ref(new Map())
provide('diffFilter', diffFilter)
provide('diffViews', diffViews)

/**
 * 每页滚动位置记忆（通用）：任何页面离开时记录 scrollY，返回时该页有记录
 * 就恢复，不限来源页；无记录的页归零。带锚点跳转（报告条目 → 差异页
 * 对应卡片）时不恢复，锚点滚动优先。
 */
const scrollMemo = new Map()
/** 切页过渡结束后待恢复的滚动位置（out-in：新页挂载晚于 active 变化一个离场过渡） */
let pendingScrollRestore = null

watch(active, (to, from) => {
  scrollMemo.set(from, window.scrollY)
  pendingScrollRestore = null
  if (pendingAnchor.value) return // 锚点跳转由 DiffPage 挂载时滚动，不恢复
  const y = scrollMemo.get(to)
  if (y != null) pendingScrollRestore = y
})

/**
 * 滚动恢复必须在新页淡入第一帧之前完成，用 enter 钩子（元素插入后、
 * 过渡开始前同步触发）；after-enter 才 scrollTo 会让新页先从头淡入
 * 约 200ms 再硬跳，肉眼可见。
 * out-in 下旧页已离场，新页内容在插入时即完成渲染，文档高度就是新页
 * 高度，此时 scrollTo 不会被钳位。
 * 没有记忆位置的页面，同一时刻归零，不残留上一页的滚动。
 * 锚点跳转（报告条目 → 差异页卡片）不在这里滚动，由 DiffPage 挂载时定位。
 */
function onPageEnter() {
  if (anchorJump) {
    anchorJump = false
    return
  }
  if (pendingScrollRestore != null) {
    window.scrollTo(0, pendingScrollRestore)
    pendingScrollRestore = null
    return
  }
  window.scrollTo(0, 0)
}

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

/** 差异页有待复核条目时才点亮，给用户一个"该去哪看"的提示。口径与差异页「需关注」一致 */
const problemCount = computed(() => {
  if (!task.value) return 0
  return task.value.comparisons?.filter(needsReview).length ?? 0
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
  /* 窄屏下顶栏页签隐藏（底部标签栏接管导航）：offsetWidth 为 0 时跳过写入，
     保留桌面端的测量结果，避免指示条被清零后回到桌面端闪跳 */
  if (el.offsetWidth === 0) return
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
  document.addEventListener('click', onDocumentClick)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  window.removeEventListener('resize', updateIndicator)
  document.removeEventListener('click', onDocumentClick)
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
        <!-- 徽标在桌面端只是标识；≤640px 时是可点按钮，开合下方的 mock-selects 弹层 -->
        <button
          type="button"
          class="flag-btn"
          :class="mock ? 'mock-flag' : 'backend-flag'"
          :title="mock ? '前端正在使用本地示例数据，未连接后端' : '前端直连后端接口，所见均为真实处理结果'"
          @click="toggleMockPanel"
        >{{ mock ? '示例数据' : '真实后端' }}</button>
        <!-- 桌面端 display:contents 平铺在顶栏；≤640px 变成徽标下方的弹层 -->
        <div class="mock-selects" :class="{ open: mockPanelOpen }">
          <div v-if="mock" class="mock-field">
            <AppSelect
              v-model="mockScenario"
              :options="scenarioOptions"
              title="选择示例场景，下次提交检查时生效"
              @change="onScenarioChange"
            />
            <p class="mock-note">选择示例场景，下次提交检查时生效</p>
          </div>
          <div class="mock-field">
            <AppSelect
              :model-value="mock ? 'mock' : 'backend'"
              :options="SOURCE_OPTIONS"
              title="切换数据来源，切换后页面自动刷新"
              @change="onSourceChange"
            />
            <p class="mock-note">切换数据来源，切换后页面自动刷新</p>
          </div>
        </div>
      </div>
    </header>

    <!-- 移动端主导航：≤640px 显示（顶栏页签隐藏），选中态用颜色/字重表达，不用滑动指示条 -->
    <nav class="bottom-tabs" aria-label="页面导航">
      <button
        v-for="p in PAGES"
        :key="p.key"
        class="bottom-tab"
        :class="{ active: active === p.key, locked: isLocked(p.key) }"
        :disabled="isLocked(p.key)"
        :title="isLocked(p.key) ? '先在上传页创建一次检查' : ''"
        @click="active = p.key"
      >
        {{ p.label }}
        <span v-if="p.key === 'diff' && problemCount" class="tab-badge">{{ problemCount }}</span>
      </button>
    </nav>

    <main class="content">
      <Transition name="fade" mode="out-in" @enter="onPageEnter">
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
