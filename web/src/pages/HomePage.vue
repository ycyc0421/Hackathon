<script setup>
/**
 * 首页：应用入口。两栏 Hero（主张 + 主操作 | 单证叠放示意）、当前任务条（有任务时）、
 * 三步流程、mock 演示场景区（示例数据模式下）。
 * 入口页允许品牌表达：Hero 示意图加载时做一次纸张散开，呼应切页的纸张层叠语言；
 * 示意图是装饰（aria-hidden），不代表任何真实任务数据。
 */
import { computed, inject } from 'vue'
import { useRouter } from 'vue-router'
import { isMock, listMockScenarios, setMockScenario } from '../api/index.js'
import { taskStatus } from '../api/formatters.js'
import { needsReview } from '../utils/needsReview.js'
import { autoSubmitMock } from '../state/session.js'
import { SCENARIO_NAMES, SCENARIO_HINTS } from '../state/scenarios.js'
import StatusBadge from '../components/StatusBadge.vue'

const router = useRouter()

/** 当前任务由上传页写入会话层；为空时任务条整条不渲染 */
const task = inject('task')

const statusInfo = computed(() => (task.value ? taskStatus(task.value.status) : null))

/** 待复核数：与差异页「需关注」、顶栏角标同一口径 */
const reviewCount = computed(() => task.value?.comparisons?.filter(needsReview).length ?? 0)

/** 继续查看去向：有待复核直接进差异页处理问题，否则看报告 */
function continueTask() {
  router.push(reviewCount.value > 0 ? '/diff' : '/report')
}

/* 图标为内联 SVG 路径（24×24 线性，stroke 继承 currentColor），不引入图标库 */
const STEPS = [
  {
    num: '01',
    title: '上传',
    desc: '拖入同一票货物的发票、箱单、提单或 EDI 报文。',
    icon: 'M12 15V4m0 0L7.5 8.5M12 4l4.5 4.5M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3',
  },
  {
    num: '02',
    title: '比对',
    desc: '逐份抽取字段，交叉比对多份单证之间是否一致。',
    icon: 'M8 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h2M16 4h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-2M9 9h6M9 12h6M9 15h3',
  },
  {
    num: '03',
    title: '报告',
    desc: '汇总冲突与风险提示，输出可存档的检查结论。',
    icon: 'M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm7 0v5h5M9 13l2 2 4-4',
  },
]

/** 演示区只在示例数据模式下出现：真实后端模式没有可预演的合成结果 */
const mock = isMock()
const scenarios = listMockScenarios().map((key) => ({
  key,
  label: SCENARIO_NAMES[key] ?? key,
  hint: SCENARIO_HINTS[key] ?? null,
  edi: key.startsWith('edi-'),
}))
const scenarioGroups = [
  { title: '常规单证', items: scenarios.filter((s) => !s.edi) },
  { title: 'EDI 报文', items: scenarios.filter((s) => s.edi) },
].filter((g) => g.items.length)

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
      <div class="home-hero-copy">
        <span class="home-eyebrow">跨境物流 · 单证交叉比对</span>
        <h1 class="home-hero-title">多份单证，<br />一次交叉比对</h1>
        <p class="home-hero-sub">
          把同一票货的发票、装箱单、提单和 EDI 报文放在一起，逐字段核对件数、重量、品名与编码，
          冲突和缺失一眼可见。
        </p>
        <div class="home-hero-actions">
          <button class="btn primary large" @click="router.push('/upload')">
            开始检查
            <svg class="btn-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m0 0-5-5m5 5-5 5" /></svg>
          </button>
          <button class="btn large" @click="router.push('/eval')">查看评测数据</button>
        </div>
        <ul class="home-formats" aria-label="支持的单证">
          <li>商业发票</li>
          <li>装箱单</li>
          <li>提单</li>
          <li>EDI 报文</li>
        </ul>
      </div>

      <!-- 装饰示意：三张单证叠放，同一字段在其中一张上不一致。不是任务数据 -->
      <div class="home-stack" aria-hidden="true">
        <div class="home-sheet sheet-3">
          <span class="sheet-tag">提单</span>
          <span class="sheet-line w-70" />
          <span class="sheet-line w-50" />
          <span class="sheet-row"><span>件数</span><b>120 CTNS</b></span>
          <span class="sheet-line w-60" />
        </div>
        <div class="home-sheet sheet-2">
          <span class="sheet-tag">装箱单</span>
          <span class="sheet-line w-60" />
          <span class="sheet-line w-80" />
          <span class="sheet-row"><span>件数</span><b>120 CTNS</b></span>
          <span class="sheet-line w-40" />
        </div>
        <div class="home-sheet sheet-1">
          <span class="sheet-tag">商业发票</span>
          <span class="sheet-line w-80" />
          <span class="sheet-line w-50" />
          <span class="sheet-row conflict"><span>件数</span><b>100 CTNS</b></span>
          <span class="sheet-line w-70" />
          <span class="sheet-line w-40" />
        </div>
        <span class="home-stack-flag">件数不一致 · 100 ≠ 120</span>
      </div>
    </section>

    <!-- 当前任务：有任务才渲染，给用户一个「回到哪」的入口 -->
    <section v-if="task" class="home-task" :class="reviewCount ? 'has-review' : ''">
      <div class="home-task-head">
        <StatusBadge :status="statusInfo" />
        <span class="home-task-id">任务 {{ task.task_id }}</span>
        <span v-if="reviewCount" class="home-task-review">{{ reviewCount }} 项待复核</span>
      </div>
      <button class="btn primary" @click="continueTask">继续查看</button>
    </section>

    <section class="home-steps">
      <div v-for="s in STEPS" :key="s.num" class="home-step">
        <div class="home-step-icon">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="s.icon" /></svg>
        </div>
        <span class="home-step-num">{{ s.num }}</span>
        <h2 class="home-step-title">{{ s.title }}</h2>
        <p class="home-step-desc">{{ s.desc }}</p>
      </div>
    </section>

    <section v-if="mock" class="home-demo">
      <div class="home-section-head">
        <h2 class="home-section-title">演示场景</h2>
        <p class="home-section-sub">当前为示例数据模式。点一个场景，直接跑完一次完整检查。</p>
      </div>
      <div v-for="g in scenarioGroups" :key="g.title" class="home-scenario-group">
        <h3 class="home-group-title">{{ g.title }}</h3>
        <div class="home-scenarios">
          <button
            v-for="sc in g.items"
            :key="sc.key"
            type="button"
            class="home-scenario"
            @click="runScenario(sc.key)"
          >
            <span class="home-scenario-name">{{ sc.label }}</span>
            <span v-if="sc.hint" class="home-scenario-desc">{{ sc.hint.desc }}</span>
            <span class="home-scenario-foot">
              <span v-if="sc.hint" class="badge" :class="`tone-${sc.hint.tone}`">{{ sc.hint.outcome }}</span>
              <span class="home-scenario-go">演示
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m0 0-5-5m5 5-5 5" /></svg>
              </span>
            </span>
          </button>
        </div>
      </div>
    </section>
  </div>
</template>
