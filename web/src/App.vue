<script setup>
import { ref, computed, provide } from 'vue'
import { USE_MOCK } from './api/index.js'
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

/** 当前检查任务。由上传页写入，差异页和报告页读取 */
const task = ref(null)
const taskError = ref(null)
const isRunning = ref(false)

provide('task', task)
provide('taskError', taskError)
provide('isRunning', isRunning)

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
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <span class="brand-mark">单证校验</span>
        <span class="brand-sub">跨境物流 · 交叉比对与合规提示</span>
      </div>

      <nav class="tabs">
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
      </nav>

      <div v-if="USE_MOCK" class="mock-flag" title="前端正在使用本地示例数据，未连接后端">
        示例数据
      </div>
    </header>

    <main class="content">
      <component :is="current" />
    </main>

    <footer class="footer">
      <span>契约草案 v0.1 · 未冻结</span>
      <span v-if="task" class="task-ref">任务 {{ task.task_id }}</span>
    </footer>
  </div>
</template>
