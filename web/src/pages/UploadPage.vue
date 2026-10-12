<script setup>
/**
 * 上传页：选择同一票货物的多份单证，创建检查任务。
 *
 * 目的国暂由用户选择。契约第四节第 3 项未定「由用户选还是从文件识别」，
 * 这里按用户选择实现——可控，演示时不依赖抽取准确率。
 */
import { ref, computed, inject, onBeforeUnmount } from 'vue'
import { createCheck, pollCheck, validateFiles, splitByName, ApiError, UPLOAD_LIMITS } from '../api/index.js'
import { backendErrorText } from '../api/errors.js'
import { taskStatus, processStatus, formatTime, formatDuration } from '../api/formatters.js'
import { API_ERROR_KIND, UPLOAD_ERROR_TEXT, TASK_STAGES, SCAN_WARNING } from '../api/labels.js'
import { detectPdfTextLayer } from '../pdfTextLayer.js'
import { needsReview } from '../utils/needsReview.js'
import { heightListItemHooks, collapseHooks } from '../utils/animateHeight.js'
import { isMobile } from '../utils/isMobile.js'
import StatusBadge from '../components/StatusBadge.vue'
import NoticeBar from '../components/NoticeBar.vue'
import SkeletonBlock from '../components/SkeletonBlock.vue'
import EmptyState from '../components/EmptyState.vue'
import AppSelect from '../components/AppSelect.vue'

const task = inject('task')
const taskError = inject('taskError')
const isRunning = inject('isRunning')
const sourceFiles = inject('sourceFiles')
/** 跨页导航：完成态 CTA 直跳差异页 */
const navigate = inject('navigate')

// 目的国列表为演示用。后端（issue #4）确认当前规则覆盖美/德/荷/法/英，
// 均为未经核实的演示规则，正式合规结论不能据此得出。
const COUNTRY_OPTIONS = [
  { value: 'US', label: '美国' },
  { value: 'DE', label: '德国' },
  { value: 'NL', label: '荷兰' },
  { value: 'FR', label: '法国' },
  { value: 'GB', label: '英国' },
]

/**
 * 表单状态由 App 层持有（provide/inject），切页返回时文件列表/目的国/备注保留，
 * 与 task 生命周期一致；scanWarnings 同样来自 App 层，见 App.vue 的说明。
 */
const files = inject('uploadFiles')
const country = inject('uploadCountry')
const notes = inject('uploadNotes')
const localErrors = ref([])
const dragActive = ref(false)
const fileInput = ref(null)

/**
 * PDF 文本层预检测命中的文件集合，key 与去重键一致（`${name}:${size}`）。
 * 只存判定为 'no-text' 的；'unknown'（查不了）一律静默，不进入集合。
 * 检测针对用户选的真实文件，与 USE_MOCK 开关无关。状态由 App 层持有。
 */
const scanWarnings = inject('uploadScanWarnings')

/** 命中预检测的文件数，供汇总提示条使用 */
const scanWarnCount = computed(() => scanWarnings.value.size)

/** 轮询超过软提示线（SLOW_POLL_MS，30s）未结束时显示"处理时间较长"，但不停止等待 */
const slowHint = ref(false)
/** 请求层自动重试进行中（网络错误 / 5xx），显示"正在重连" */
const retryHint = ref(false)

// —— 进度展示状态 ——
// phase：idle 无任务；uploading 正在传文件；processing 已创建任务、轮询中
const phase = ref('idle')
const uploadPercent = ref(null)
const startedAt = ref(null)
const now = ref(Date.now())
let clockTimer = null

/**
 * 提交入口以当前文件集合实时跑 validateFiles 为准：
 * 不满足阻塞性限制（0 份 / 超份数 / 超大小）时按钮禁用，
 * 不能只依赖 addFiles 时算过的 localErrors——那之后文件可能已被移除或追加。
 * 扫描件预检测警告不在此列（非阻塞提示）。
 */
const canSubmit = computed(() => !isRunning.value && validateFiles(files.value).length === 0)

const acceptedTypes = computed(() =>
  UPLOAD_LIMITS.accept.split(',').map((s) => s.trim().toUpperCase().replace('.', ''))
)

function isAccepted(file) {
  const ext = file.name.split('.').pop()?.toUpperCase() ?? ''
  return acceptedTypes.value.includes(ext)
}

function isPdf(file) {
  return file.name.split('.').pop()?.toUpperCase() === 'PDF'
}

function fileKey(f) {
  return `${f.name}:${f.size}`
}

/**
 * 对单个 PDF 做文本层预检测。只警告、不阻止：
 * - 命中 'no-text' → 加入 scanWarnings，界面显示警告
 * - 'text' / 'unknown' → 从集合移除（unknown 静默降级，绝不误报）
 */
async function scanOne(file) {
  const result = await detectPdfTextLayer(file)
  const key = fileKey(file)
  // 检测是异步的，出结果时文件可能已被用户移除——不回写已移除文件的警告
  if (!files.value.some((f) => fileKey(f) === key)) return
  const next = new Set(scanWarnings.value)
  if (result === 'no-text') next.add(key)
  else next.delete(key)
  scanWarnings.value = next
}

/**
 * 调度预检测：等条目进入动画结束、浏览器空闲时再跑。
 * 检测要读文件并解压内容流（已在 pdfTextLayer 里限制只扫前 4MB），
 * 若与动画同帧抢主线程，添加文件的补间会掉帧。
 */
function scheduleScan(file) {
  const run = () => scanOne(file)
  if (typeof requestIdleCallback === 'function') {
    requestIdleCallback(run, { timeout: 900 })
  } else {
    setTimeout(run, 350)
  }
}

function addFiles(list) {
  localErrors.value = []
  const incoming = Array.from(list)

  const rejected = incoming.filter((f) => !isAccepted(f))
  if (rejected.length) {
    localErrors.value.push(
      UPLOAD_ERROR_TEXT.UNSUPPORTED_FORMAT(
        rejected.map((f) => f.name).join('、'),
        UPLOAD_LIMITS.accept
      )
    )
  }

  const accepted = incoming.filter(isAccepted)
  // 同名即歧义：「查看原文」按文件名关联本地 File 对象，契约没有更可靠的
  // 文件身份可用，同名文件会让映射互相覆盖、打开错原文——按文件名拒绝，
  // 让用户重命名后再添加，而不是静默接受或猜测 file_id。
  const { fresh, duplicateNames } = splitByName(files.value, accepted)
  if (duplicateNames.length) {
    localErrors.value.push(UPLOAD_ERROR_TEXT.DUPLICATE_NAME(duplicateNames.join('、')))
  }
  files.value = [...files.value, ...fresh]

  const problems = validateFiles(files.value)
  if (problems.length) localErrors.value.push(...problems)

  // 只对 PDF 做文本层预检测，图片（本来就没有文本层）不检测。
  // 异步后台跑，不阻塞文件进入列表；检测失败在 detectPdfTextLayer 内部降级为 unknown。
  for (const f of fresh) {
    if (isPdf(f)) scheduleScan(f)
  }
}

function onDrop(e) {
  dragActive.value = false
  addFiles(e.dataTransfer?.files ?? [])
}

function onPick(e) {
  addFiles(e.target.files ?? [])
  e.target.value = '' // 允许再次选择同一文件
}

function removeFile(index) {
  const removed = files.value[index]
  files.value = files.value.filter((_, i) => i !== index)
  // 复验剩余文件而不是清空错误：移除一个正常文件后，其余超限文件的错误必须还在
  localErrors.value = files.value.length ? validateFiles(files.value) : []
  // 同步清理预检测记录，避免残留警告指向已移除的文件
  if (removed && scanWarnings.value.has(fileKey(removed))) {
    const next = new Set(scanWarnings.value)
    next.delete(fileKey(removed))
    scanWarnings.value = next
  }
}

function clearAll() {
  files.value = []
  notes.value = ''
  localErrors.value = []
  scanWarnings.value = new Set()
  // 「查看原文」依赖这份映射，文件清了映射也要清
  sourceFiles.clear()
}

function sizeText(bytes) {
  const mb = bytes / 1024 / 1024
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${(bytes / 1024).toFixed(0)} KB`
}

/** 网络错误 / 5xx 触发自动重试时的提示开关。只在真正进入重试时才亮起 */
function onAutoRetry() {
  retryHint.value = true
}

function startClock() {
  startedAt.value = Date.now()
  now.value = Date.now()
  clockTimer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
}

function stopClock() {
  if (clockTimer) {
    clearInterval(clockTimer)
    clockTimer = null
  }
}

onBeforeUnmount(stopClock)

/** 已等待时长文案。只展示真实流逝的时间，不做任何预计（后端没有给 ETA 数据） */
const elapsedText = computed(() => {
  if (!startedAt.value) return ''
  const totalSec = Math.max(0, Math.floor((now.value - startedAt.value) / 1000))
  if (totalSec < 60) return `${totalSec} 秒`
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return `${m} 分 ${s} 秒`
})

/**
 * 推断当前处于哪个阶段，返回 TASK_STAGES 的下标。
 * 契约没有显式 stage 字段，按任务状态与逐文件 process_status 推断；
 * -1 表示任务尚未创建（还在上传文件）。
 */
const stageIndex = computed(() => {
  if (phase.value === 'uploading') return -1
  const t = task.value
  if (!t) return 0
  if (t.status === 'PENDING') return 0
  if (t.status === 'PROCESSING') {
    const docs = t.documents ?? []
    if (docs.length && docs.every((d) => d.process_status === 'EXTRACTED')) return 2
    return 1
  }
  return TASK_STAGES.length - 1
})

/** 骨架屏行数与已选文件数一致，占位形状贴近真实列表 */
const skeletonRows = computed(() => Math.max(files.value.length, 2))

async function submit() {
  // 直接调用 submit 也不能绕过校验：以当前文件集合实时复验为准
  const problems = validateFiles(files.value)
  if (isRunning.value) return
  if (problems.length) {
    localErrors.value = problems
    return
  }

  // 提交即把当前文件写入 App 层映射：diff 页「查看原文」按文件名从这里取 File。
  // mock 场景 files 为空（mock 不经真实上传），映射随之清空，按钮自然不渲染。
  sourceFiles.setAll(files.value)

  localErrors.value = []
  taskError.value = null
  task.value = null
  slowHint.value = false
  retryHint.value = false
  isRunning.value = true
  phase.value = 'uploading'
  uploadPercent.value = null
  startClock()

  try {
    const created = await createCheck(
      {
        files: files.value,
        destinationCountry: country.value,
        notes: notes.value,
      },
      {
        onRetry: onAutoRetry,
        onUploadProgress: (p) => {
          uploadPercent.value = p
        },
      }
    )

    phase.value = 'processing'

    const result = await pollCheck(created.task_id, {
      onTick: (t) => {
        task.value = t
        // 拿到一次响应说明重试结束了（如果之前在重试）
        retryHint.value = false
      },
      onSlow: () => {
        slowHint.value = true
      },
      onRetry: onAutoRetry,
    })

    task.value = result
  } catch (e) {
    // 失败必须显式呈现。绝不能落到"结果为空 → 页面显示没有问题"。
    // 服务端错误按后端错误码换成面向用户的中文文案（api/errors.js），
    // 查不到映射时用后端给的 message 兜底，不把英文 code 甩给用户。
    taskError.value =
      e instanceof ApiError
        ? {
            message: e.kind === 'SERVER' ? backendErrorText(e) : e.message,
            kind: e.kind,
            code: e.code,
          }
        : { message: e?.message ?? '未知错误', kind: 'UNKNOWN' }
  } finally {
    isRunning.value = false
    phase.value = 'idle'
    stopClock()
  }
}

const statusInfo = computed(() => (task.value ? taskStatus(task.value.status) : null))

/**
 * 任务是否未达终态。慢提示/重连提示的显示条件以此为准，
 * 而不是"task 对象是否存在"——首次 onTick 写入 task 后提示不能消失。
 */
const TERMINAL_STATUSES = ['COMPLETED', 'PARTIAL', 'FAILED']
const taskPending = computed(() => !task.value || !TERMINAL_STATUSES.includes(task.value.status))

/** taskError 的分类展示：标题、语气、建议动作统一由 labels.js 的 API_ERROR_KIND 决定 */
const taskErrorInfo = computed(() => {
  if (!taskError.value) return null
  if (taskError.value.kind === 'UNKNOWN') {
    return { tone: API_ERROR_KIND.UNKNOWN.tone, title: API_ERROR_KIND.UNKNOWN.title, hint: API_ERROR_KIND.UNKNOWN.hint }
  }
  const entry = API_ERROR_KIND[taskError.value.kind] ?? API_ERROR_KIND.UNKNOWN
  return { tone: entry.tone, title: entry.title, hint: entry.hint }
})
const duration = computed(() =>
  task.value ? formatDuration(task.value.created_at, task.value.finished_at) : null
)
const failedDocs = computed(
  () =>
    task.value?.documents?.filter(
      (d) => d.process_status === 'FAILED' || d.process_status === 'UNSUPPORTED'
    ) ?? []
)

/**
 * 进行态下逐文件的真实状态列表。后端一旦返回 documents 就用它替换骨架屏，
 * 每轮轮询就地刷新（解析中 → 已抽取），让用户看到任务确实在推进。
 */
const liveDocs = computed(() => task.value?.documents ?? [])

/**
 * 进行态文件行：与终态完全同一结构（左文件名、右状态徽章），从上传到终态零跳变。
 * 后端还没返回 documents 时（上传中 / 排队中）先用本地已选文件的名字占位——
 * 文件名是前端一提交就知道的信息，不该用骨架屏藏着。
 */
const displayDocs = computed(() => {
  if (liveDocs.value.length) {
    return liveDocs.value.map((d) => ({
      key: d.file_id,
      name: d.file_name,
      error: d.error_message,
      status: processStatus(d.process_status),
    }))
  }
  return files.value.map((f) => ({
    key: fileKey(f),
    name: f.name,
    error: null,
    status: phase.value === 'uploading'
      ? { text: '上传中', tone: 'running' }
      : { text: '排队中', tone: 'muted' },
  }))
})

/** 解析进度计数：已抽取 x / n 份，任务进入 PROCESSING 且后端回了 documents 时展示 */
const extractProgress = computed(() => {
  if (!liveDocs.value.length) return null
  const done = liveDocs.value.filter(
    (d) => d.process_status === 'EXTRACTED' || d.process_status === 'FAILED' || d.process_status === 'UNSUPPORTED'
  ).length
  return { done, total: liveDocs.value.length }
})

/** 待复核条目数：与差异页「需关注」、顶栏角标同一口径 */
const reviewCount = computed(() => task.value?.comparisons?.filter(needsReview).length ?? 0)
</script>

<template>
  <div class="page">
    <section class="card">
      <h2 class="card-title">创建检查</h2>
      <p class="card-sub">选择属于同一票货物的多份单证。系统将逐份抽取字段，再交叉比对它们之间是否一致。</p>

      <!-- 文件选择。role=button + tabindex 保证键盘可达：Enter/Space 打开文件选择 -->
      <div
        class="dropzone"
        :class="{ active: dragActive }"
        role="button"
        tabindex="0"
        aria-label="选择或拖入单证文件"
        @dragover.prevent="dragActive = true"
        @dragleave.prevent="dragActive = false"
        @drop.prevent="onDrop"
        @click="fileInput?.click()"
        @keydown.enter.prevent="fileInput?.click()"
        @keydown.space.prevent="fileInput?.click()"
      >
        <!-- 手机没有拖放，窄屏只提示点击选择 -->
        <div class="dropzone-main">{{ isMobile ? '点击选择文件' : '把文件拖到这里，或点击选择' }}</div>
        <div class="dropzone-hint">
          支持 {{ UPLOAD_LIMITS.accept.split(',').join(' / ') }}，单个不超过
          {{ UPLOAD_LIMITS.maxFileSizeMB }}MB，最多 {{ UPLOAD_LIMITS.maxFiles }} 份
        </div>
        <input
          ref="fileInput"
          type="file"
          multiple
          :accept="UPLOAD_LIMITS.accept"
          class="hidden-input"
          @change="onPick"
        />
      </div>

      <!--
        文件列表增删动画：TransitionGroup + 稳定 key（fileKey，不带下标——
        删中间项时按下标做 key 会让后续条目全部重键、补位动画失效）。
        进入/离开走 JS 精确高度钩子（utils/animateHeight.js 的 heightListItemHooks，
        :css="false"）：条目留在文档流内，高度/padding/边框与透明度同步收放，
        栏位与文字一体，兄弟行随高度变化自然移动。
        容器常驻挂载（不用 v-if）：v-if 会在删到最后一项时把 ul 直接移除，
        条目离场钩子不执行、只剩窗口 resize；空态用 .file-list--empty 把
        边框与 margin 一并过渡，首尾项的增删与中间项同样连贯。
        不加 appear：切页重挂载时已有文件不应重播进入动画（appear 的语义
        就是每次挂载都播），条目插入本身就会触发进入钩子。
      -->
      <TransitionGroup
        tag="ul"
        class="file-list"
        :class="{ 'file-list--empty': !files.length }"
        :css="false"
        v-bind="heightListItemHooks"
      >
        <li v-for="(f, i) in files" :key="fileKey(f)" class="file-item">
          <span class="file-name">{{ f.name }}</span>
          <span
            v-if="scanWarnings.has(`${f.name}:${f.size}`)"
            class="scan-warn"
            :title="SCAN_WARNING.badgeTitle"
            >{{ SCAN_WARNING.badge }}</span
          >
          <span class="file-size">{{ sizeText(f.size) }}</span>
          <button class="link-btn" @click="removeFile(i)">移除</button>
        </li>
      </TransitionGroup>

      <div class="field-row">
        <label class="field">
          <span class="field-label">目的国</span>
          <AppSelect
            v-model="country"
            block
            :options="COUNTRY_OPTIONS"
          />
          <span class="field-label">规则覆盖范围为演示配置，未经核实，不作为正式合规结论。</span>
        </label>

        <label class="field field-grow">
          <span class="field-label">备注（可选）</span>
          <input v-model="notes" class="input" placeholder="例如：提单是手机拍摄的扫描件" />
        </label>
      </div>

      <!-- 校验错误与扫描警告：整块出现/消失走 collapse 收合动画，
           不硬插硬撤（与文件列表同一套收放语义，见 utils/animateHeight.js） -->
      <Transition :css="false" v-bind="collapseHooks">
        <NoticeBar
          v-if="localErrors.length"
          tone="warn"
          title="请先处理以下问题"
        >
          <ul class="notice-list">
            <li v-for="(e, i) in localErrors" :key="i">{{ e }}</li>
          </ul>
        </NoticeBar>
      </Transition>

      <!-- 扫描件预检测警告：只提示，不影响 canSubmit，用户仍可提交 -->
      <Transition :css="false" v-bind="collapseHooks">
        <NoticeBar
          v-if="scanWarnCount"
          tone="warn"
          :title="SCAN_WARNING.title"
          :detail="SCAN_WARNING.detail(scanWarnCount)"
        />
      </Transition>

      <div class="actions">
        <button class="btn primary" :disabled="!canSubmit" @click="submit">
          {{ isRunning ? '处理中…' : '开始检查' }}
        </button>
        <button class="btn" :disabled="isRunning || (!files.length && !notes)" @click="clearAll">
          清空
        </button>
      </div>
    </section>

    <!-- 初始引导：尚未创建过检查时，说明支持什么、怎么开始 -->
    <EmptyState
      v-if="!isRunning && !task && !taskError"
      tone="info"
      title="尚未上传单证"
      :detail="`把同一票货物的发票、箱单、提单等单证拖到上方虚线框，选好目的国后点「开始检查」。支持 ${UPLOAD_LIMITS.accept.split(',').join(' / ')}，单个不超过 ${UPLOAD_LIMITS.maxFileSizeMB}MB，最多 ${UPLOAD_LIMITS.maxFiles} 份。`"
    />

    <!-- 任务状态 -->
    <section v-if="isRunning || task || taskError" class="card">
      <h2 class="card-title">任务状态</h2>

      <!-- 三类状态在同一区域淡出→淡入，切换时标题与卡片保持不动 -->
      <Transition name="fade" mode="out-in">
        <!-- 失败：显式呈现，绝不显示为通过。标题/说明统一来自 labels.js 的分类文案 -->
        <div v-if="taskError" key="error" class="task-status-body">
          <NoticeBar :tone="taskErrorInfo.tone" :title="taskErrorInfo.title">
            <p class="notice-detail">{{ taskError.message }}</p>
            <p v-if="taskErrorInfo.hint" class="notice-detail">{{ taskErrorInfo.hint }}</p>
            <div class="actions">
              <button class="btn small" :disabled="!canSubmit" @click="submit">重试</button>
            </div>
          </NoticeBar>
        </div>

        <!--
          任务全生命周期单视图：进行中 → 终态不换分支、不整体刷新。
          各区域就地更新——阶段条常驻（终态全部置完成）、文件列表行结构
          全程一致、终态才出现的区块（警示条 / CTA / 耗时）各自动画入场。
          只有错误态例外，整区淡出替换。
        -->
        <div v-else key="task" class="task-status-body">
          <!-- 任务创建后出现头部；「耗时」在终态淡入，不硬插 -->
          <div v-if="task" class="status-row">
            <StatusBadge :status="statusInfo" />
            <span class="status-meta">任务 {{ task.task_id }}</span>
            <Transition name="fade">
              <span v-if="duration" class="status-meta">耗时 {{ duration }}</span>
            </Transition>
            <span class="status-meta">创建于 {{ formatTime(task.created_at) }}</span>
          </div>

          <!--
            阶段条常驻：进行态标出当前阶段（活动点脉冲），终态全部置为完成——
            它是任务走过路径的记录。FAILED 没走完流程，不展示。
          -->
          <div class="stage-header">
            <ol v-if="task?.status !== 'FAILED'" class="stage-row">
              <li
                v-for="(s, i) in TASK_STAGES"
                :key="s.key"
                class="stage-item"
                :class="{
                  done: i < stageIndex || !taskPending,
                  active: taskPending && i === stageIndex,
                }"
              >
                <span class="stage-dot" aria-hidden="true" />
                <span class="stage-text">{{ s.text }}</span>
              </li>
            </ol>
            <Transition name="fade">
              <span v-if="taskPending" class="wait-line">已等待 {{ elapsedText }}</span>
            </Transition>
          </div>

          <!--
            上传进度条：仅代表「文件字节传到后端」的进度，与任务处理进度无关。
            100% 只说明字节发完了，浏览器还在等 /checks 创建任务的响应——
            此时把百分比换成「等待创建任务」，避免"拉满了却没开始"的误读。
            进度条只在上传阶段存在；结束时高度收起而不是瞬间消失。
          -->
          <div class="upload-progress-wrap" :class="{ collapsed: phase !== 'uploading' }">
            <div class="upload-progress">
              <span class="progress-label">上传文件</span>
              <div class="progress-track">
                <div
                  class="progress-fill"
                  :style="{ width: `${uploadPercent ?? 0}%` }"
                  role="progressbar"
                  :aria-valuenow="uploadPercent ?? 0"
                  aria-valuemin="0"
                  aria-valuemax="100"
                />
              </div>
              <span class="progress-num" :class="{ 'progress-num--text': uploadPercent === null || uploadPercent >= 100 }">
                {{ uploadPercent === null ? '连接中…' : uploadPercent >= 100 ? '等待创建任务…' : `${uploadPercent}%` }}
              </span>
            </div>
          </div>

          <p v-if="taskPending && retryHint" class="processing-hint">网络异常，正在自动重连…</p>
          <p v-else-if="taskPending && slowHint" class="processing-hint">
            处理时间较长，仍在等待。可以继续留在本页，也可以稍后回来查看。
          </p>

          <!-- 终态警示条：收合动画入场，不硬插（部分成功是最容易做成静默忽略的状态） -->
          <Transition :css="false" v-bind="collapseHooks">
            <NoticeBar
              v-if="task?.status === 'PARTIAL'"
              tone="warn"
              title="本次检查未包含全部文件"
              :detail="`${failedDocs.length} 份文件未能处理成功。以下比对结果缺少这些文件的数据，不代表它们一致。`"
            />
          </Transition>
          <Transition :css="false" v-bind="collapseHooks">
            <NoticeBar
              v-if="task?.status === 'FAILED'"
              tone="bad"
              title="检查失败"
              detail="未产生任何比对结果。请检查文件格式后重试。"
            />
          </Transition>

          <!--
            文件列表全程同一结构（左文件名、右状态徽章），零跳变：
            - 后端未返回 documents：用本地已选文件的真实文件名，状态为上传中/排队中
            - 后端已返回 documents：随每轮轮询就地刷新（解析中 → 已抽取/处理失败）
            处理进度计数紧贴列表上方， spinner 标明仍在处理；
            只有完全拿不到文件名时（mock 未选文件）才落回骨架屏。
          -->
          <p v-if="taskPending && extractProgress" class="extract-progress">
            <span class="inline-spinner" aria-hidden="true" />
            已处理 {{ extractProgress.done }} / {{ extractProgress.total }} 份文件
          </p>
          <ul v-if="displayDocs.length" class="doc-list">
            <li v-for="d in displayDocs" :key="d.key" class="doc-item">
              <div class="doc-main">
                <span class="doc-name">{{ d.name }}</span>
                <span v-if="d.error" class="doc-error">{{ d.error }}</span>
              </div>
              <span class="doc-status">
                <span v-if="d.status.tone === 'running'" class="inline-spinner" aria-hidden="true" />
                <StatusBadge :status="d.status" />
              </span>
            </li>
          </ul>
          <ul v-else class="doc-list skeleton-list" aria-hidden="true">
            <li v-for="i in skeletonRows" :key="i" class="doc-item">
              <SkeletonBlock width="42%" height="13px" />
              <SkeletonBlock width="56px" height="20px" />
            </li>
          </ul>

          <!-- 完成态主路径：收合动画入场，直接给去差异页的按钮 -->
          <Transition :css="false" v-bind="collapseHooks">
            <div
              v-if="task && (task.status === 'COMPLETED' || task.status === 'PARTIAL')"
              class="next-actions"
            >
              <button class="btn primary" @click="navigate.go('diff')">
                {{ reviewCount > 0 ? `查看待复核项（${reviewCount}）` : '查看比对结果' }}
              </button>
              <p class="next-hint">差异页默认按「需关注」筛选，可切换查看全部比对。</p>
            </div>
          </Transition>
        </div>
      </Transition>
    </section>
  </div>
</template>
