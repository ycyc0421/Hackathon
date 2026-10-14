<script setup>
/**
 * 首页：应用入口。两栏 Hero（主张 + 主操作 | 单证叠放示意）、当前任务条（有任务时）、
 * 核心能力交替大行、并排比对预览、三步流程、mock 演示场景区（示例数据模式下）。
 *
 * 入口页允许品牌表达（DESIGN.md「入口级 vs 功能页」）：Hero 示意图加载时散开一次，
 * 随后由扫描线做一轮循环（唯一允许循环的动效，承担"系统正在核对"的叙事）；
 * 各区块滚动进入视口时上浮淡入。示意图与预览区都是装饰（aria-hidden），
 * 不代表任何真实任务数据。
 */
import { computed, inject, onMounted, onBeforeUnmount, ref } from 'vue'
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

/* 核心能力：交替左右大行。illustration 是纯 CSS 插图的种类标识，不引图片资源 */
const FEATURES = [
  {
    kind: 'ocr',
    title: 'OCR 智能识别',
    desc: '支持文本层 PDF、图片单证与扫描件。保留原始读数与页码定位，无法识别时如实提示，不伪造结果。',
    points: ['文本层 PDF 直读，图片与扫描件走 OCR 识别', '有页码与坐标时，可回溯到原件位置'],
  },
  {
    kind: 'compare',
    title: '多文件交叉比对',
    desc: '同时上传商业发票、装箱单、提单和 EDI 报文，逐字段归一化后精确对照。多商品行按货号分组对齐，行序变化不影响结果。',
    points: ['件数、重量、金额、币种、HS 编码', '不一致与部分缺失分开标注，不混为一谈'],
  },
  {
    kind: 'rules',
    title: '规则合规提示',
    desc: '根据目的国与商品编码提示待复核事项，并附带规则依据。演示规则仅作辅助参考，不替代正式合规审查。',
    points: ['覆盖美、德、荷、法、英五国演示规则', '依据规则的提示与未经规则校验的建议分开呈现'],
  },
  {
    kind: 'report',
    title: '可存档报告',
    desc: '汇总不一致、缺失与风险提示，保留原文证据与来源文件。支持导出自包含 HTML 报告（可打印为 PDF）或完整归档 JSON。',
    points: ['结论先于统计数字，一眼可见', '来源可溯，问题可直达差异页定位'],
  },
]

/* 三步流程：图标为内联 SVG 路径（24×24 线性，stroke 继承 currentColor），不引入图标库 */
const STEPS = [
  {
    num: '01',
    title: '上传',
    desc: '拖入同一票货物的发票、装箱单、提单或 EDI 报文。',
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
    desc: '汇总差异与风险提示，输出可存档的检查结论。',
    icon: 'M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm7 0v5h5M9 13l2 2 4-4',
  },
]

/* 并排比对预览：三份单证并置，同一字段在其中一份上不一致。
   硬编码示意数据，页脚已注明「不代表真实任务结果」 */
const PREVIEW_DOCS = [
  {
    name: '商业发票',
    type: 'COMMERCIAL_INVOICE',
    fields: [
      { label: 'HS 编码', value: '8471.30.00', tone: 'match' },
      { label: '件数', value: '100 CTNS', tone: 'conflict' },
      { label: '净重', value: '2,400 KG', tone: 'match' },
      { label: '目的港', value: 'DEHAM', tone: 'match' },
    ],
  },
  {
    name: '装箱单',
    type: 'PACKING_LIST',
    fields: [
      { label: 'HS 编码', value: '8471.30.00', tone: 'match' },
      { label: '件数', value: '120 CTNS', tone: 'match' },
      { label: '净重', value: '2,400 KG', tone: 'match' },
      { label: '目的港', value: 'DEHAM', tone: 'match' },
    ],
  },
  {
    name: '提单',
    type: 'BILL_OF_LADING',
    fields: [
      { label: 'HS 编码', value: '8471.30.00', tone: 'match' },
      { label: '件数', value: '120 CTNS', tone: 'match' },
      { label: '净重', value: '2,400 KG', tone: 'match' },
      { label: '目的港', value: 'DEHAM', tone: 'match' },
    ],
  },
]

/** 演示视频：由 scripts/record-demo.mjs 录到 public/，用相对路径引用 */
const DEMO_SRC = './demo.mp4'
const DEMO_POSTER = './demo-poster.jpg'

/**
 * 是否渲染"看一次完整的使用"这一块。两条独立的回退路径：
 *
 * 1. **构建期开关**：`VITE_HOME_DEMO=0 npm run build` 直接不渲染。
 *    用于"这一版就是不要视频"的场景。
 * 2. **运行期自动回退**：视频文件加载失败（还没出片、被清理、网络失败）
 *    时自动收起整块。`public/` 不参与打包，构建期无法可靠探测文件是否存在，
 *    所以这件事只能在运行期做——而它也正是最需要的那条路径：视频 PR 与
 *    UI PR 是分开交付的，UI 先发时 mp4 还没落地，页面必须自己回退。
 *
 * 两条路径都让整块**连同标题一起**消失，首页回到没有视频时的样子；
 * 它上下两块各自带 64px 留白，少一段不会塌陷错位。
 */
const demoEnabled = import.meta.env.VITE_HOME_DEMO !== '0'
const demoFailed = ref(false)
const showDemo = computed(() => demoEnabled && !demoFailed)

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

/**
 * 滚动揭示：区块进入视口后上浮淡入。
 *
 * 关键设计：**默认可见，只在需要时才隐藏**。挂载时只给"确实在视口下方"
 * 的元素加 .reveal--armed（即 CSS 里唯一会 opacity:0 的类），滚动到时再加
 * .is-in 恢复。反过来做（默认隐藏、等 JS 揭示）一旦观察器漏触发——快速
 * 跳转滚动、打印、脚本未执行——内容就永久隐形了。动画只能是增强，
 * 不能成为内容可见的前提。
 */
const rootEl = ref(null)
let observer = null

onMounted(() => {
  const targets = rootEl.value?.querySelectorAll('.reveal')
  if (!targets?.length) return
  if (typeof IntersectionObserver === 'undefined') return

  // 首屏内已经可见的区块不参与动画，直接以最终态呈现
  const pending = [...targets].filter(
    (el) => el.getBoundingClientRect().top > window.innerHeight * 0.9,
  )
  if (!pending.length) return

  pending.forEach((el) => el.classList.add('reveal--armed'))
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        entry.target.classList.add('is-in')
        observer.unobserve(entry.target)
      }
    },
    { rootMargin: '0px 0px -10% 0px', threshold: 0.06 },
  )
  pending.forEach((el) => observer.observe(el))
})

onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <div ref="rootEl" class="page home">
    <!-- 首屏：Hero + 流程条。整块高度撑满可视区（减去顶栏与内容内边距），
         因此下半区永远从折叠线以下开始，不滚动看不到——
         "入口"和"展开说明"在视觉与结构上是两件事。 -->
    <div class="home-top">
    <section class="home-hero">
      <div class="home-hero-copy">
        <span class="home-eyebrow">跨境物流 · 单证交叉比对</span>
        <h1 class="home-hero-title">
          多份单证，<br />一次找出<em>冲突</em>
        </h1>
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

      <!-- 装饰示意：三张单证叠放，同一字段在其中一张上不一致。
           不是任务数据，aria-hidden -->
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

    <!-- 三步流程：紧接 Hero，回答"这东西怎么用"。连接线先画完，图标依次浮现 -->
    <section class="home-steps">
      <div v-for="(s, i) in STEPS" :key="s.num" class="home-step" :style="`--step-i:${i}`">
        <div class="home-step-icon">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="s.icon" /></svg>
        </div>
        <span class="home-step-num">{{ s.num }}</span>
        <h2 class="home-step-title">{{ s.title }}</h2>
        <p class="home-step-desc">{{ s.desc }}</p>
      </div>
    </section>
    </div><!-- /.home-top -->

    <!-- ============ 折叠线以下：滚动才进入视野 ============
         整个下半区包一层 .home-below，与 Hero 在结构上分开：
         它自带上方留白，负责把"入口"和"展开说明"隔开。 -->
    <div class="home-below">

    <!-- 真实使用演示：完整走一遍上传 → 比对 → 报告。
         视频由 scripts/record-demo.mjs 录到 public/demo.mp4，录好即生效。

         开关的意义：演示视频的产出在另一条线上（录制需要浏览器与 ffmpeg，
         在 CI 里是独立的一环），随时可能还没生成或需要回退。所以这里
         用一个显式开关而不是"文件在不在"来决定要不要渲染这一整块——
         回退时整段连同标题一起消失，首页回到没有视频时的样子；
         它上下两块各自有 64px 的留白，不会因为少了一段而塌陷错位。 -->
    <section v-if="showDemo" class="home-demo-video reveal" aria-label="使用演示">
      <div class="home-section-head">
        <h2 class="home-section-title">看一次完整的使用</h2>
        <p class="home-section-sub">上传三份单证、跑完比对、在报告里看到冲突与风险提示。</p>
      </div>
      <figure class="demo-frame">
        <!-- 用绑定写法（:src）而不是静态 src：静态值会被 Vite 当作模块资源解析，
            而 public/ 下的文件不参与打包，直接引用会构建失败。
             绑定值保持运行时相对路径，配合 base:'./' 与 hash 路由正确解析。 -->
        <video
          class="demo-video"
          :src="DEMO_SRC"
          :poster="DEMO_POSTER"
          controls
          muted
          loop
          playsinline
          preload="metadata"
          @error="demoFailed = true"
        />
        <figcaption class="demo-caption">
          演示使用内置示例数据，不包含任何真实单证内容。
        </figcaption>
      </figure>
    </section>

    <!-- 核心能力：交替左右大行，插图纯 CSS -->
    <section class="home-features" aria-label="核心功能">
      <div class="home-section-head">
        <h2 class="home-section-title">为什么用它核对单证</h2>
        <p class="home-section-sub">不是把文件摆在一起看，而是逐字段算出它们哪里不一致。</p>
      </div>

      <article
        v-for="(f, i) in FEATURES"
        :key="f.title"
        class="feature-row reveal"
        :class="i % 2 ? 'feature-row--flip' : ''"
        :style="`--reveal-delay:${(i % 2) * 90}ms`"
      >
        <div class="feature-illus" :class="`feature-illus--${f.kind}`" aria-hidden="true">
          <!-- OCR：一张扫描件 + 扫过的识别光带 + 落下的字段 chip -->
          <template v-if="f.kind === 'ocr'">
            <div class="illus-doc">
              <span class="illus-line w-70" /><span class="illus-line w-50" />
              <span class="illus-line w-80" /><span class="illus-line w-40" />
            </div>
            <div class="illus-scan" />
            <span class="illus-chip chip-a">件数 120</span>
            <span class="illus-chip chip-b">净重 2,400</span>
          </template>

          <!-- 比对：三份单证连到一个中心节点，其中一条链路标红 -->
          <template v-else-if="f.kind === 'compare'">
            <div class="illus-node" />
            <span class="illus-sheet s-a">发票</span>
            <span class="illus-sheet s-b">装箱单</span>
            <span class="illus-sheet s-c">提单</span>
            <span class="illus-link l-a" /><span class="illus-link l-b" /><span class="illus-link l-c" />
          </template>

          <!-- 规则：一张规则卡 + 命中的两条，一条通过一条告警 -->
          <template v-else-if="f.kind === 'rules'">
            <div class="illus-rule rule-ok"><span class="rule-dot" />HS 编码格式校验通过</div>
            <div class="illus-rule rule-warn"><span class="rule-dot" />目的国需原产地证明</div>
            <div class="illus-rule rule-mute"><span class="rule-dot" />未配置该类目归类规则</div>
          </template>

          <!-- 报告：一页报告 + 结论条 + 存档印章 -->
          <template v-else>
            <div class="illus-doc illus-doc--report">
              <span class="illus-line w-60" />
              <span class="illus-conclusion" />
              <span class="illus-line w-80" /><span class="illus-line w-50" />
            </div>
            <span class="illus-seal">存档</span>
          </template>
        </div>

        <div class="feature-copy">
          <h3 class="feature-title">{{ f.title }}</h3>
          <p class="feature-desc">{{ f.desc }}</p>
          <ul class="feature-points">
            <li v-for="p in f.points" :key="p">{{ p }}</li>
          </ul>
        </div>
      </article>
    </section>

    <!-- 并排比对预览：三份单证并置，冲突字段在其中一份上高亮 -->
    <section class="home-preview reveal" aria-label="比对预览示意">
      <div class="home-section-head">
        <h2 class="home-section-title">字段级精准比对</h2>
        <p class="home-section-sub">逐份抽取、归一化后对照，不一致的那份文件被点出来。</p>
      </div>

      <div class="home-compare" aria-hidden="true">
        <article
          v-for="doc in PREVIEW_DOCS"
          :key="doc.name"
          class="compare-doc"
        >
          <header class="compare-doc-head">
            <span class="compare-doc-name">{{ doc.name }}</span>
            <span class="compare-doc-type">{{ doc.type }}</span>
          </header>
          <dl class="compare-fields">
            <div
              v-for="fld in doc.fields"
              :key="fld.label"
              class="compare-field"
              :class="fld.tone === 'conflict' ? 'is-conflict' : ''"
            >
              <dt>{{ fld.label }}</dt>
              <dd>{{ fld.value }}</dd>
            </div>
          </dl>
        </article>
      </div>

      <p class="home-preview-note">示意数据，不代表真实任务结果</p>
    </section>

    <section v-if="mock" class="home-demo reveal">
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
    </div><!-- /.home-below -->
  </div>
</template>
