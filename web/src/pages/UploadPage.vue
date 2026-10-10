<script setup>
/**
 * 上传页：选择同一票货物的多份单证，创建检查任务。
 *
 * 目的国暂由用户选择。契约第四节第 3 项未定「由用户选还是从文件识别」，
 * 这里按用户选择实现——可控，演示时不依赖抽取准确率。
 */
import { ref, computed, inject, onBeforeUnmount } from 'vue'
import { createCheck, pollCheck, validateFiles, ApiError, UPLOAD_LIMITS, USE_MOCK } from '../api/index.js'
import { taskStatus, processStatus, formatTime, formatDuration, describeApiError } from '../api/formatters.js'
import { API_ERROR_KIND, UPLOAD_ERROR_TEXT, TASK_STAGES } from '../api/labels.js'
import StatusBadge from '../components/StatusBadge.vue'
import NoticeBar from '../components/NoticeBar.vue'
import SkeletonBlock from '../components/SkeletonBlock.vue'
import EmptyState from '../components/EmptyState.vue'

const task = inject('task')
const taskError = inject('taskError')
const isRunning = inject('isRunning')

// 目的国列表为演示用。后端（issue #4）确认当前规则覆盖美/德/荷/法/英，
// 均为未经核实的演示规则，正式合规结论不能据此得出。
const COUNTRIES = [
  { code: 'US', name: '美国' },
  { code: 'DE', name: '德国' },
  { code: 'NL', name: '荷兰' },
  { code: 'FR', name: '法国' },
  { code: 'GB', name: '英国' },
]

const files = ref([])
const country = ref('DE')
const notes = ref('')
const localErrors = ref([])
const dragActive = ref(false)
const fileInput = ref(null)

/** 轮询超过 90s 未结束时显示"处理时间较长"，但不停止等待 */
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

const canSubmit = computed(() => files.value.length > 0 && !isRunning.value)

const acceptedTypes = computed(() =>
  UPLOAD_LIMITS.accept.split(',').map((s) => s.trim().toUpperCase().replace('.', ''))
)

function isAccepted(file) {
  const ext = file.name.split('.').pop()?.toUpperCase() ?? ''
  return acceptedTypes.value.includes(ext)
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
  // 同名文件去重，避免重复上传造成"件数不一致"的假象
  const seen = new Set(files.value.map((f) => `${f.name}:${f.size}`))
  const fresh = accepted.filter((f) => !seen.has(`${f.name}:${f.size}`))
  files.value = [...files.value, ...fresh]

  const problems = validateFiles(files.value)
  if (problems.length) localErrors.value.push(...problems)
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
  files.value = files.value.filter((_, i) => i !== index)
  localErrors.value = []
}

function clearAll() {
  files.value = []
  notes.value = ''
  localErrors.value = []
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
  if (!canSubmit.value) return

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
    // 失败必须显式呈现。绝不能落到"结果为空 → 页面显示没有问题"
    taskError.value =
      e instanceof ApiError
        ? { message: e.message, kind: e.kind, code: e.code }
        : { message: e?.message ?? '未知错误', kind: 'UNKNOWN' }
  } finally {
    isRunning.value = false
    phase.value = 'idle'
    stopClock()
  }
}

const statusInfo = computed(() => (task.value ? taskStatus(task.value.status) : null))

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

/** 逐文件处理状态的展示对象 */
function docStatus(d) {
  return processStatus(d.process_status)
}
</script>

<template>
  <div class="page">
    <section class="card">
      <h2 class="card-title">创建检查</h2>
      <p class="card-sub">选择属于同一票货物的多份单证。系统将逐份抽取字段，再交叉比对它们之间是否一致。</p>

      <!-- 文件选择 -->
      <div
        class="dropzone"
        :class="{ active: dragActive }"
        @dragover.prevent="dragActive = true"
        @dragleave.prevent="dragActive = false"
        @drop.prevent="onDrop"
        @click="fileInput?.click()"
      >
        <div class="dropzone-main">把文件拖到这里，或点击选择</div>
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

      <ul v-if="files.length" class="file-list">
        <li v-for="(f, i) in files" :key="`${f.name}-${i}`" class="file-item">
          <span class="file-name">{{ f.name }}</span>
          <span class="file-size">{{ sizeText(f.size) }}</span>
          <button class="link-btn" @click="removeFile(i)">移除</button>
        </li>
      </ul>

      <div class="field-row">
        <label class="field">
          <span class="field-label">目的国</span>
          <select v-model="country" class="input">
            <option v-for="c in COUNTRIES" :key="c.code" :value="c.code">{{ c.name }}</option>
          </select>
          <span class="field-label">规则覆盖范围为演示配置，未经核实，不作为正式合规结论。</span>
        </label>

        <label class="field field-grow">
          <span class="field-label">备注（可选）</span>
          <input v-model="notes" class="input" placeholder="例如：提单是手机拍摄的扫描件" />
        </label>
      </div>

      <NoticeBar
        v-if="localErrors.length"
        tone="warn"
        title="请先处理以下问题"
      >
        <ul class="notice-list">
          <li v-for="(e, i) in localErrors" :key="i">{{ e }}</li>
        </ul>
      </NoticeBar>

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
      icon="📄"
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

        <div v-else-if="task" key="result" class="task-status-body">
          <div class="status-row">
            <StatusBadge :status="statusInfo" />
            <span class="status-meta">任务 {{ task.task_id }}</span>
            <span v-if="duration" class="status-meta">耗时 {{ duration }}</span>
            <span class="status-meta">创建于 {{ formatTime(task.created_at) }}</span>
          </div>

          <!-- 部分成功：最容易做成静默忽略的状态 -->
          <NoticeBar
            v-if="task.status === 'PARTIAL'"
            tone="warn"
            title="本次检查未包含全部文件"
            :detail="`${failedDocs.length} 份文件未能处理成功。以下比对结果缺少这些文件的数据，不代表它们一致。`"
          />

          <NoticeBar
            v-if="task.status === 'FAILED'"
            tone="bad"
            title="检查失败"
            detail="未产生任何比对结果。请检查文件格式后重试。"
          />

          <ul class="doc-list">
            <li v-for="d in task.documents" :key="d.file_id" class="doc-item">
              <div class="doc-main">
                <span class="doc-name">{{ d.file_name }}</span>
                <span v-if="d.error_message" class="doc-error">{{ d.error_message }}</span>
              </div>
              <StatusBadge :status="docStatus(d)" />
            </li>
          </ul>

          <p v-if="task.status === 'COMPLETED' || task.status === 'PARTIAL'" class="next-hint">
            已生成比对结果，切到「差异」页查看。
          </p>
        </div>

        <!-- 处理中：分阶段进度 + 上传百分比 + 已等待时长 + 骨架屏 -->
        <div v-else key="processing" class="task-status-body">
          <div class="stage-header">
            <ol class="stage-row">
              <li
                v-for="(s, i) in TASK_STAGES"
                :key="s.key"
                class="stage-item"
                :class="{ done: i < stageIndex, active: i === stageIndex }"
              >
                <span class="stage-dot" aria-hidden="true" />
                <span class="stage-text">{{ s.text }}</span>
              </li>
            </ol>
            <span class="wait-line">已等待 {{ elapsedText }}</span>
          </div>

          <!-- 进度条只在上传阶段存在；结束时高度收起而不是瞬间消失 -->
          <div class="upload-progress-wrap" :class="{ collapsed: phase !== 'uploading' }">
            <div class="upload-progress">
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
              <span class="progress-num">
                {{ uploadPercent === null ? '上传中…' : `${uploadPercent}%` }}
              </span>
            </div>
          </div>

          <p v-if="retryHint" class="processing-hint">网络异常，正在自动重连…</p>
          <p v-else-if="slowHint" class="processing-hint">
            处理时间较长，仍在等待。可以继续留在本页，也可以稍后回来查看。
          </p>

          <ul class="doc-list skeleton-list" aria-hidden="true">
            <li v-for="i in skeletonRows" :key="i" class="doc-item">
              <SkeletonBlock width="42%" height="13px" />
              <SkeletonBlock width="56px" height="20px" />
            </li>
          </ul>
        </div>
      </Transition>
    </section>
  </div>
</template>
