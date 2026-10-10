<script setup>
/**
 * 上传页：选择同一票货物的多份单证，创建检查任务。
 *
 * 目的国暂由用户选择。契约第四节第 3 项未定「由用户选还是从文件识别」，
 * 这里按用户选择实现——可控，演示时不依赖抽取准确率。
 */
import { ref, computed, inject } from 'vue'
import { createCheck, pollCheck, validateFiles, ApiError, UPLOAD_LIMITS, USE_MOCK } from '../api/index.js'
import { taskStatus, processStatus, formatTime, formatDuration } from '../api/formatters.js'
import StatusBadge from '../components/StatusBadge.vue'
import NoticeBar from '../components/NoticeBar.vue'

const task = inject('task')
const taskError = inject('taskError')
const isRunning = inject('isRunning')

// 目的国列表为演示用。契约第四节第 3 项未定实际支持范围，需后端侧确认。
const COUNTRIES = [
  { code: 'DE', name: '德国' },
  { code: 'NL', name: '荷兰' },
  { code: 'US', name: '美国' },
  { code: 'JP', name: '日本' },
]

const files = ref([])
const country = ref('DE')
const notes = ref('')
const localErrors = ref([])
const dragActive = ref(false)
const fileInput = ref(null)

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
      `格式不支持：${rejected.map((f) => f.name).join('、')}。支持 ${UPLOAD_LIMITS.accept}`
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

async function submit() {
  if (!canSubmit.value) return

  localErrors.value = []
  taskError.value = null
  task.value = null
  isRunning.value = true

  try {
    const created = await createCheck({
      files: files.value,
      destinationCountry: country.value,
      notes: notes.value,
    })

    const result = await pollCheck(created.task_id, {
      onTick: (t) => {
        task.value = t
      },
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
  }
}

const statusInfo = computed(() => (task.value ? taskStatus(task.value.status) : null))
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

    <!-- 任务状态 -->
    <section v-if="isRunning || task || taskError" class="card">
      <h2 class="card-title">任务状态</h2>

      <!-- 失败：显式呈现，绝不显示为通过 -->
      <NoticeBar
        v-if="taskError"
        tone="bad"
        :title="`检查未能完成：${taskError.message}`"
        :detail="
          taskError.kind === 'NETWORK'
            ? '前端未收到后端响应。请确认服务已启动、代理配置正确。'
            : taskError.kind === 'TIMEOUT'
              ? '等待超过 90 秒。后端可能仍在处理，可稍后重试。'
              : '请将上述信息提供给后端同学排查。'
        "
      />

      <template v-else-if="task">
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
      </template>

      <!-- 处理中 -->
      <div v-else class="processing">
        <div class="spinner" />
        <span>正在解析与比对…</span>
      </div>
    </section>
  </div>
</template>
