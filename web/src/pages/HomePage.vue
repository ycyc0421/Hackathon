<script setup>
/**
 * 首页：应用入口。Hero + 主操作、当前任务卡（有任务时）、三步流程说明、
 * mock 演示场景区（示例数据模式下）。入口页不放装饰动画，加载即所见。
 */
import { computed, inject } from 'vue'
import { useRouter } from 'vue-router'
import { isMock, listMockScenarios, setMockScenario } from '../api/index.js'
import { taskStatus } from '../api/formatters.js'
import { needsReview } from '../utils/needsReview.js'
import { autoSubmitMock } from '../state/session.js'
import { SCENARIO_NAMES } from '../state/scenarios.js'
import StatusBadge from '../components/StatusBadge.vue'

const router = useRouter()

/** 当前任务由上传页写入会话层；为空时任务卡整张不渲染 */
const task = inject('task')

const statusInfo = computed(() => (task.value ? taskStatus(task.value.status) : null))

/** 待复核数：与差异页「需关注」、顶栏角标同一口径 */
const reviewCount = computed(() => task.value?.comparisons?.filter(needsReview).length ?? 0)

/** 继续查看去向：有待复核直接进差异页处理问题，否则看报告 */
function continueTask() {
  router.push(reviewCount.value > 0 ? '/diff' : '/report')
}

const STEPS = [
  { num: '01', title: '上传', desc: '拖入同一票货物的发票、箱单、提单或 EDI 报文。' },
  { num: '02', title: '比对', desc: '逐份抽取字段，交叉比对多份单证之间是否一致。' },
  { num: '03', title: '报告', desc: '汇总冲突与风险提示，输出可存档的检查结论。' },
]

/** 演示区只在示例数据模式下出现：真实后端模式没有可预演的合成结果 */
const mock = isMock()
const scenarios = listMockScenarios().map((key) => ({
  key,
  label: SCENARIO_NAMES[key] ?? key,
}))

/**
 * 点场景卡：设定场景后跳上传页，由上传页挂载时自动提交一次检查。
 * 提交动作放在上传页执行——进度过程（上传 → 解析 → 比对）本身就是演示的一部分。
 */
function runScenario(key) {
  setMockScenario(key)
  autoSubmitMock.value = key
  router.push('/upload')
}
</script>

<template>
  <div class="page home">
    <section class="home-hero">
      <h1 class="home-hero-title">多份单证，一次交叉比对</h1>
      <p class="home-hero-sub">装箱单 · 发票 · 提单 · EDI 报文</p>
      <div class="home-hero-actions">
        <button class="btn primary" @click="router.push('/upload')">开始检查 →</button>
        <button class="link-btn" @click="router.push('/eval')">查看评测数据</button>
      </div>
    </section>

    <!-- 当前任务：有任务才渲染，给用户一个「回到哪」的入口 -->
    <section v-if="task" class="card home-task">
      <div class="home-task-head">
        <StatusBadge :status="statusInfo" />
        <span class="home-task-id">任务 {{ task.task_id }}</span>
        <span v-if="reviewCount" class="home-task-review">{{ reviewCount }} 项待复核</span>
      </div>
      <button class="btn" @click="continueTask">继续查看</button>
    </section>

    <section class="home-steps">
      <div v-for="s in STEPS" :key="s.num" class="card home-step">
        <span class="home-step-num">{{ s.num }}</span>
        <h2 class="home-step-title">{{ s.title }}</h2>
        <p class="home-step-desc">{{ s.desc }}</p>
      </div>
    </section>

    <section v-if="mock" class="home-demo">
      <h2 class="card-title">演示场景</h2>
      <p class="card-sub">当前为示例数据模式。选择一个场景，直接演示一次完整检查流程。</p>
      <div class="home-scenarios">
        <button
          v-for="sc in scenarios"
          :key="sc.key"
          type="button"
          class="home-scenario"
          @click="runScenario(sc.key)"
        >
          {{ sc.label }}
        </button>
      </div>
    </section>
  </div>
</template>
