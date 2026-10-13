<script setup>
import { ref, computed, provide, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { isMock, getEvaluation, getCheck } from './api/index.js'
import { needsReview } from './utils/needsReview.js'
import {
  task, taskError, isRunning,
  uploadFiles, uploadCountry, uploadNotes, uploadScanWarnings,
  diffFilter, diffViews,
  evaluation, evaluationLoaded,
  pendingAnchor,
} from './state/session.js'
import { theme, toggleTheme } from './state/theme.js'
import ErrorBoundary from './components/ErrorBoundary.vue'

/* label 从路由 meta 取，这里只存页序 key 列表，避免两处维护同一份文案 */
const PAGES = [
  { key: 'upload', label: '上传' },
  { key: 'diff', label: '差异' },
  { key: 'report', label: '报告' },
  { key: 'eval', label: '评测' },
]

const route = useRoute()
const router = useRouter()
const active = computed(() => route.name)

/**
 * 任务恢复（main 引入）：URL 只保存任务编号，刷新后重新读取后端结果。
 * 顶栏的数据源切换 UI 已移除（改用 ?mock=1 URL 参数），
 * 这里只保留恢复逻辑本身。
 */
const mock = isMock()
const restoreError = ref('')
const terminalStatuses = new Set(['COMPLETED', 'PARTIAL', 'FAILED'])
// URL 仅保存任务编号，刷新后重新读取后端结果。
watch(() => [task.value?.task_id, task.value?.status], ([id]) => {
  if (isMock()) return
  if (id) restoreError.value = ''
  const url = new URL(window.location.href)
  if (id && terminalStatuses.has(task.value?.status)) url.searchParams.set('task', id)
  else if (!id) url.searchParams.delete('task')
  // 保留 Vue Router 的历史状态，避免破坏前进、后退和滚动恢复。
  window.history.replaceState(window.history.state, '', url)
})
onMounted(async () => {
  if (isMock()) return
  const id = new URLSearchParams(window.location.search).get('task')
  if (!id) return
  if (!/^tsk_[A-Za-z0-9_-]{1,100}$/.test(id)) {
    restoreError.value = '任务编号格式无效，请重新上传或检查链接。'
    return
  }
  isRunning.value = true
  try {
    await router.isReady()
    const restored = await getCheck(id)
    if (!terminalStatuses.has(restored.status)) {
      restoreError.value = '此任务尚未结束，请稍后刷新查看结果。'
      return
    }
    task.value = restored
    await router.replace({ name: 'report' })
  } catch (error) {
    restoreError.value = `无法恢复任务：${error.message || '请检查网络或任务链接'}`
  } finally { isRunning.value = false }
})

/** 当前检查任务。由上传页写入，差异页和报告页读取（ref 本体在 state/session.js） */
provide('task', task)
provide('taskError', taskError)
provide('isRunning', isRunning)

/**
 * 上传页表单状态提升到会话层（state/session.js）：文件列表/目的国/备注在
 * 切页返回时保留，与任务状态（task）的生命周期一致。
 */
provide('uploadFiles', uploadFiles)
provide('uploadCountry', uploadCountry)
provide('uploadNotes', uploadNotes)
provide('uploadScanWarnings', uploadScanWarnings)

/**
 * 跨页导航：报告页的条目可以直接跳到差异页对应位置。
 * anchor 经 pendingAnchor 传给目标页（页面随切页重挂载，挂载时消费并清空）。
 * go 的签名不变，页面零改动；内部从改 active ref 换成 router.push。
 */
/** 本次切页是否锚点跳转：是则滚动交给目标页挂载时的锚点定位，进场钩子不碰滚动 */
let anchorJump = false

function go(page, anchor) {
  pendingAnchor.value = anchor ?? null
  anchorJump = !!anchor
  router.push({ name: page })
}

provide('pendingAnchor', pendingAnchor)
provide('navigate', { go })

/** 差异页筛选与每张卡片的 表格/对照 选择（ref 本体在 state/session.js） */
provide('diffFilter', diffFilter)
provide('diffViews', diffViews)

/**
 * 每页滚动位置记忆（通用）：任何页面离开时记录 scrollY，返回时该页有记录
 * 就恢复，不限来源页；无记录的页归零。带锚点跳转（报告条目 → 差异页
 * 对应卡片）时不恢复，锚点滚动优先。
 */
const scrollMemo = new Map()
/**
 * 切页过渡的滚动恢复目标（纸张层叠：enter 钩子里同步 scrollTo，见下）。
 * enter 时新页已插入、旧页已 fixed 脱流不撑高，文档高度即新页内容高度，
 * 此时 scrollTo 不会被钳位。注意不能放在 before-enter：那时新页尚未插入，
 * 旧页又已脱流，文档只剩顶栏+页脚，maxScroll≈0，scrollTo 会被立即钳到 0。
 */
let pendingScrollRestore = null

/**
 * 纸张层叠方向：按路由 meta.order 比较 from/to 得出前进/后退，
 * 动态切换两套过渡类。首页 order 最小（-1），去向任何页都是前进；
 * 锚点跳转（报告页 → 差异页条目，order 2 → 1）按同一规则算为后退。
 */
const pageTransition = ref('page-stack-forward')
/** 层叠进行中：.content 显出底下的「桌面」暗层，两张纸的边缘和缩小后的留白才看得见 */
const stacking = ref(false)
const orderOf = (name) =>
  router.getRoutes().find((r) => r.name === name)?.meta?.order ?? 0

watch(() => route.name, (to, from) => {
  pageTransition.value =
    orderOf(to) >= orderOf(from) ? 'page-stack-forward' : 'page-stack-backward'
  scrollMemo.set(from, window.scrollY)
  pendingScrollRestore = null
  if (pendingAnchor.value) return // 锚点跳转由 DiffPage 挂载时滚动，不恢复
  const y = scrollMemo.get(to)
  if (y != null) pendingScrollRestore = y
})

/** 首次挂载不做焦点迁移（见 onPageEnter） */
let firstPageEnter = true

/**
 * 滚动恢复新时序（并行过渡，不再是 out-in）：
 * enter 在新页插入后、过渡开始前同步触发，此刻旧页已 fixed 脱流、
 * 文档高度即新页高度，立即 scrollTo 不会钳位，也赶得上进场第一帧。
 * 有记忆位置恢复记忆，否则归零；锚点跳转不在这里滚动，
 * DiffPage 挂载时的锚点定位优先于滚动记忆。
 *
 * 焦点迁移：页内按钮触发跳页后旧页卸载，焦点会回落到 body，
 * 键盘/读屏用户位置丢失。切页后把焦点移到新页第一个标题
 * （tabindex=-1 只收程序焦点，不进 Tab 序），preventScroll 不与
 * 滚动恢复打架。首次挂载不动焦点（浏览器原生恢复行为优先）。
 */
function onPageEnter(el) {
  if (anchorJump) {
    anchorJump = false
  } else {
    const y = pendingScrollRestore
    pendingScrollRestore = null
    window.scrollTo(0, y ?? 0)
  }
  /* 后退时新纸从「被压低」状态放大回来：缩放原点对准视口中心而不是纸张
     中心（长页面的纸张中心可能远在视口外，缩放会带着可见区域大幅漂移）。
     用未受 transform 影响的 offsetTop 推算纸张在视口中的位置 */
  /* 后退进场：压缩状态回弹放大。版心内容列居中，以自身中点为原点即可 */
  el.style.transformOrigin = '50% 50%'  
  if (firstPageEnter) {
    firstPageEnter = false
    return
  }
  const heading = el.querySelector?.('h1, h2')
  if (!heading) return
  heading.tabIndex = -1
  heading.focus({ preventScroll: true })
}

/**
 * 旧页脱流：量出视口位置后用 fixed 锁定（top 已是视口坐标，天然补偿了
 * scrollY，before-enter 的 scrollTo 不会带它走），旧页在视觉原位缩小/
 * 滑出，不随新页滚动位置跳。宽度锁为实测宽，防止脱流后宽度塌陷。
 */
function onPageBeforeLeave(el) {
  const rect = el.getBoundingClientRect()
  el.style.position = 'fixed'
  el.style.top = `${rect.top}px`
  el.style.left = `${rect.left}px`
  el.style.width = `${rect.width}px`
  el.style.margin = '0'
  /* 缩放原点对齐视口中心（版心内容列，不是整屏），长页面滚动后不会漂移 */
  el.style.transformOrigin = `50% ${window.innerHeight / 2 - rect.top}px`
  stacking.value = true
}

/**
 * 清理脱流内联样式。元素本身会被 Vue 移除，这里是防御性清理：
 * 离场被取消（leave-cancelled）时元素会留在 DOM，样式必须还原；
 * prefers-reduced-motion 下过渡近瞬切，同样不能残留 fixed。
 */
function onPageLeaveDone(el) {
  el.style.position = ''
  el.style.top = ''
  el.style.left = ''
  el.style.width = ''
  el.style.margin = ''
  el.style.transformOrigin = ''
  stacking.value = false
}

/** 进场结束（或被打断）清掉缩放原点，静止态不留内联样式 */
function onPageAfterEnter(el) {
  el.style.transformOrigin = ''
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

/** 评测数据缓存提升到会话层（state/session.js），重挂载时直接复用 */
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

const current = computed(() => route.matched.at(-1)?.components?.default)

/** 没有任务时，差异页和报告页没有内容可显示；首页是入口，恒不锁定 */
function isLocked(key) {
  if (key === 'home') return false
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
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  window.removeEventListener('resize', updateIndicator)
})

watch(() => route.name, updateIndicator)
</script>

<template>
  <ErrorBoundary>
    <div class="app">
      <!-- 桌面层的第二团光晕：与 .app::before 的蓝光形成对角 -->
      <span class="desk-glow" aria-hidden="true" />

      <header class="topbar">
      <!-- 品牌区做成可点按钮：任何页面都可回首页，入口语义一致 -->
      <button type="button" class="brand" @click="router.push({ name: 'home' })">
        <span class="brand-mark-icon" aria-hidden="true" />
        <span class="brand-text">
          <span class="brand-mark">单证校验</span>
          <span class="brand-sub">跨境物流 · 交叉比对与合规提示</span>
        </span>
      </button>

      <!-- 首页是入口页，不渲染顶栏页签（含指示条），减少干扰 -->
      <nav v-if="active !== 'home'" ref="tabsRef" class="tabs">
        <button
          v-for="p in PAGES"
          :key="p.key"
          class="tab"
          :class="{ active: active === p.key, locked: isLocked(p.key) }"
          :disabled="isLocked(p.key)"
          :title="isLocked(p.key) ? '先在上传页创建一次检查' : ''"
          @click="router.push({ name: p.key })"
        >
          {{ p.label }}
          <span v-if="p.key === 'diff' && problemCount" class="tab-badge">{{ problemCount }}</span>
        </button>
        <span class="tab-indicator" :style="indicatorStyle" aria-hidden="true" />
      </nav>

      <!-- 主题切换：放在顶栏最右，与导航分离。
           aria-pressed 表达"暗色是否开启"，图标是纯 CSS 的日/月。 -->
      <button
        type="button"
        class="theme-toggle"
        :aria-pressed="theme === 'dark'"
        :title="theme === 'dark' ? '切换到浅色' : '切换到暗色'"
        :aria-label="theme === 'dark' ? '切换到浅色主题' : '切换到暗色主题'"
        @click="toggleTheme"
      >
        <span class="theme-icon" aria-hidden="true" />
      </button>

    </header>
    <p v-if="mock" class="mock-notice" role="status">示例数据模式：结果与处理过程均为模拟，不代表真实检查或评测。</p>

    <!-- 移动端主导航：≤640px 显示（顶栏页签隐藏），选中态用颜色/字重表达，不用滑动指示条 -->
    <nav v-if="active !== 'home'" class="bottom-tabs" aria-label="页面导航">
      <button
        v-for="p in PAGES"
        :key="p.key"
        class="bottom-tab"
        :class="{ active: active === p.key, locked: isLocked(p.key) }"
        :disabled="isLocked(p.key)"
        :title="isLocked(p.key) ? '先在上传页创建一次检查' : ''"
        @click="router.push({ name: p.key })"
      >
        {{ p.label }}
        <span v-if="p.key === 'diff' && problemCount" class="tab-badge">{{ problemCount }}</span>
      </button>
    </nav>

    <main class="content" :class="{ stacking }">
      <p v-if="restoreError" role="alert">{{ restoreError }}</p>
      <!-- 纸张层叠：无 mode 并行渲染，新旧页同时在 DOM。每页包一张通栏不透明
           的 .page-inner 作为纸面（版心限宽卡片容器），层叠时两张纸
           互不透字；旧纸在 before-leave 里 fixed 脱流锁定视觉原位 -->
      <Transition
        :name="pageTransition"
        @enter="onPageEnter"
        @after-enter="onPageAfterEnter"
        @enter-cancelled="onPageAfterEnter"
        @before-leave="onPageBeforeLeave"
        @after-leave="onPageLeaveDone"
        @leave-cancelled="onPageLeaveDone"
      >
        <div :key="route.name" class="page-inner">
          <component :is="current" />
        </div>
      </Transition>
    </main>


    </div>
  </ErrorBoundary>
</template>
