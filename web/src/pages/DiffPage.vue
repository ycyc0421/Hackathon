<script setup>
/**
 * 差异页：展示抽取字段与跨文件比对结果。
 *
 * 设计要点：
 * - 逐条比对都要能回答「哪份文件、什么值、是否一致」，不允许只给一个笼统的红色提示。
 * - MATCH 之外的每种状态都要显示，尤其 NOT_CHECKED（未校验）——
 *   它必须与「没有问题」在视觉上区分开。
 */
import { ref, computed, inject, onMounted, nextTick } from 'vue'
import {
  comparisonStatus,
  fieldStatus,
  severity,
  formatValue,
  confidenceText,
} from '../api/formatters.js'
import { divergentFileIds } from '../utils/divergence.js'
import { needsReview } from '../utils/needsReview.js'
import { animateHeightAdaptive, captureHeight } from '../utils/animateHeight.js'
import { buildEvidenceIndex, evidenceRawText } from '../utils/evidence.js'
import StatusBadge from '../components/StatusBadge.vue'
import NoticeBar from '../components/NoticeBar.vue'
import SkeletonBlock from '../components/SkeletonBlock.vue'
import EmptyState from '../components/EmptyState.vue'
import ComparePane from '../components/ComparePane.vue'
import ViewSwitch from '../components/ViewSwitch.vue'

/** 视图切换分段控件的选项，值与 views Map 里存的 key 一致 */
const VIEW_OPTIONS = [
  { value: 'table', label: '表格' },
  { value: 'compare', label: '对照' },
]

const task = inject('task')
const isRunning = inject('isRunning')

/** all | problems | conflicts | unchecked。状态由 App 层持有，切页返回时保留 */
const filter = inject('diffFilter')

const comparisons = computed(() => task.value?.comparisons ?? [])

const counts = computed(() => {
  const list = comparisons.value
  return {
    total: list.length,
    problems: list.filter(needsReview).length,
    conflict: list.filter((c) => c.status === 'CONFLICT').length,
    missing: list.filter((c) => c.status === 'MISSING_IN_SOME').length,
    unchecked: list.filter((c) => c.status === 'NOT_CHECKED').length,
    unrecognized: list.filter((c) => c.status === 'UNRECOGNIZED').length,
    match: list.filter((c) => c.status === 'MATCH').length,
    single: list.filter((c) => c.status === 'SINGLE_SOURCE').length,
  }
})

const visible = computed(() => {
  const list = comparisons.value
  switch (filter.value) {
    case 'problems':
      return list.filter(needsReview)
    case 'conflicts':
      return list.filter((c) => c.status === 'CONFLICT')
    case 'unchecked':
      return list.filter((c) => c.status === 'NOT_CHECKED')
    default:
      return list
  }
})

/** 商品目录。后端没返回 items（或为空）时降级为扁平列表，行为与之前一致 */
const items = computed(() => task.value?.items ?? [])

/** 整票级比对（item_id 为 null）以及找不到对应商品的 item_id 都归到这一组 */
const SHIPMENT_GROUP_KEY = '__shipment__'

/**
 * 按商品分组的比对列表。
 * - 有 items：按 items 顺序每组一段，整票字段排在最后；
 * - 没有 items：单一匿名分组，不渲染分组头，DOM 与之前的扁平列表一致。
 * 分组基于筛选后的 visible，筛选对所有分组生效，空分组不显示。
 */
const groups = computed(() => {
  const list = visible.value
  if (!items.value.length) {
    return [{ key: '__all__', title: '', list }]
  }
  const byItem = new Map(items.value.map((it) => [it.item_id, { key: it.item_id, title: it.display_name || it.item_id, list: [] }]))
  const shipment = { key: SHIPMENT_GROUP_KEY, title: '整票字段', list: [] }
  for (const c of list) {
    const g = c.item_id != null ? byItem.get(c.item_id) : null
    ;(g ?? shipment).list.push(c)
  }
  const out = [...byItem.values()].filter((g) => g.list.length)
  if (shipment.list.length) out.push(shipment)
  return out
})

/**
 * 只有一个分组时不显示分组头：单品名且没有整票字段时和现在长得一样；
 * 多品名、或单品名同时存在整票字段时才需要分组头做区分。
 */
const showGroupTitle = computed(() => groups.value.length > 1 || items.value.length > 1)

function fileStatusOf(v) {
  return fieldStatus(v.field_status)
}

function valueText(v, comparison) {
  const { main, sub } = formatValue(v.normalized_value, comparison.value_type, comparison.unit)
  return sub ? `${main} ${sub}` : main
}

/** 归一值与原文写法不同时，把原文也显示出来，便于人工核对 */
function showsRaw(v, comparison) {
  if (!v.raw_value) return false
  const { main } = formatValue(v.normalized_value, comparison.value_type, comparison.unit)
  return String(v.raw_value).trim() !== String(main).trim()
}

/**
 * 抽取层原文证据索引：raw_value 读不出值时，回退展示抽取层保留的 raw_text。
 * 关联键为 file_id + item_id + field_key，多商品不串证据（见 utils/evidence.js）。
 */
const evidenceIndex = computed(() => buildEvidenceIndex(task.value?.extractions))

/** 该值对应的抽取层原文片段；没有证据时为 null（如实显示无证据） */
function rawEvidence(c, v) {
  return evidenceRawText(evidenceIndex.value, c, v)
}

const severityOf = severity

/** 页面头的任务短号：完整编号放 title，行内只显示末 6 位够定位即可 */
const taskShortId = computed(() => {
  const id = task.value?.task_id
  return id ? id.slice(-6) : ''
})
const docCount = computed(() => task.value?.documents?.length ?? 0)

/**
 * 每张比对卡片的当前视图：'table'（四行表格，默认）| 'compare'（并排对照）。
 * 两者是同一信息的两种排布、互为切换，不是概要/详情的展开关系，
 * 因此用分段控件切换而不是展开箭头。状态由 App 层持有（new Map 整体
 * 赋值保持响应式），切页返回时各卡片的选择保留。
 */
const views = inject('diffViews')

function viewOf(c) {
  return views.value.get(c.comparison_id) ?? 'table'
}

/**
 * 切换视图的高度衔接（距离自适应）：旧内容直接移除、新内容快速淡入
 * （--duration-fast，见 .cmp-swap 样式），高度差 ≤ 阈值时容器由
 * animateHeightAdaptive 从旧高度动画到新高度；差值过大（如长表格 ↔ 短对照）
 * 不做高度补间、容器直接到位，页面变短悬空时滚动补偿到本卡片可见。
 * 不做离场动画、不用 absolute 定位——crossfade 会让父容器高度在过渡中途
 * 坍缩，与高度动画打架，表现为整列抖动。宁可简单稳定。
 */
async function setView(c, mode, ev) {
  if (mode === viewOf(c)) return
  const item = ev?.currentTarget?.closest('.cmp-item')
  const body = item?.querySelector('.cmp-view-body')
  const fromH = captureHeight(body)
  views.value = new Map(views.value).set(c.comparison_id, mode)
  await nextTick()
  animateHeightAdaptive(body, fromH, item)
}

/**
 * 筛选 chips 切换的高度衔接（距离自适应）：筛选后的列表包在 out-in
 * Transition 里，旧内容离场结束、新内容插入的瞬间容器高度会跳变。
 * 点击时记录容器旧高度，新内容插入（enter 钩子）后由 animateHeightAdaptive
 * 分流：高度差 ≤ 阈值做高度补间；差值过大（如「全部」↔「不一致」）
 * 不补间、直接到位，页面变短悬空时滚动补偿到筛选卡片可见。
 * 注意测量目标是外层持久存在的 .cmp-filter-clip，不是 .cmp-filtered
 * 本身——后者带 :key，切换时整个元素会被替换。
 */
const filterClipRef = ref(null)
let filterFromH = null

function setFilter(name) {
  if (name === filter.value) return
  filterFromH = captureHeight(filterClipRef.value)
  filter.value = name
}

function onFilterEnter() {
  const clip = filterClipRef.value
  animateHeightAdaptive(clip, filterFromH, clip?.closest('.card'))
  filterFromH = null
}

/**
 * 收起态表格的差异强调：与多数派不同的值标红，
 * 不展开也能定位到「哪份文件不一样」。判定规则与展开的并排面板共用。
 */
function isDivergentValue(c, v) {
  return divergentFileIds(c).has(v.file_id)
}

/**
 * 报告页「在差异页查看」的锚点：页面随切页重挂载，挂载时消费一次。
 * 目标条目必然在「需关注」集合里（报告页问题条目与这里的筛选同用 needsReview 判定），
 * 先切筛选再等渲染，滚动到位后短暂高亮。
 */
const pendingAnchor = inject('pendingAnchor')

onMounted(async () => {
  if (!pendingAnchor?.value) return
  const targetId = `cmp-${pendingAnchor.value}`
  pendingAnchor.value = null
  filter.value = 'problems'
  await nextTick()
  const el = document.getElementById(targetId)
  if (!el) return
  // 平滑滚动同样尊重 prefers-reduced-motion（CSS 媒体查询管不到 JS 滚动）
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  el.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'center' })
  el.classList.add('cmp-highlight')
  setTimeout(() => el.classList.remove('cmp-highlight'), 1600)
})
</script>

<template>
  <div class="page">
    <!-- 任务进行中且没有旧结果：按比对卡片的形状占位 -->
    <section v-if="!task && isRunning" class="card" aria-hidden="true">
      <div class="skeleton-chips">
        <SkeletonBlock v-for="i in 4" :key="i" width="76px" height="26px" radius="lg" />
      </div>
      <div class="skeleton-cmp">
        <SkeletonBlock width="55%" height="16px" />
        <SkeletonBlock height="96px" />
      </div>
      <div class="skeleton-cmp">
        <SkeletonBlock width="45%" height="16px" />
        <SkeletonBlock height="96px" />
      </div>
    </section>

    <NoticeBar
      v-else-if="!task"
      tone="info"
      title="尚无检查结果"
      detail="请先在「上传」页创建一次检查。"
    />

    <template v-else>
      <!-- 页面头：标题 + 任务上下文。字级与报告页的卡片标题同一 scale，不喧宾夺主 -->
      <header class="page-head">
        <h2 class="page-title">差异比对</h2>
        <p class="page-sub" :title="`任务 ${task.task_id}`">
          任务 {{ taskShortId }} · {{ docCount }} 份文件
        </p>
      </header>

      <!-- PARTIAL 必须在差异页也提醒一次，用户可能直接跳到这里 -->
      <NoticeBar
        v-if="task.status === 'PARTIAL'"
        tone="warn"
        title="本次结果不完整"
        detail="有文件未能处理成功，相关比对缺少这些文件的数据。"
      />
      <NoticeBar
        v-else-if="task.status === 'FAILED'"
        tone="bad"
        title="检查失败"
        detail="未产生比对结果。"
      />

      <section v-if="comparisons.length" class="card">
        <div class="filter-row">
          <button class="chip" :class="{ active: filter === 'problems' }" @click="setFilter('problems')">
            需关注 <span class="chip-num">{{ counts.problems }}</span>
          </button>
          <button class="chip" :class="{ active: filter === 'conflicts' }" @click="setFilter('conflicts')">
            不一致 <span class="chip-num">{{ counts.conflict }}</span>
          </button>
          <button class="chip" :class="{ active: filter === 'unchecked' }" @click="setFilter('unchecked')">
            未校验 <span class="chip-num">{{ counts.unchecked }}</span>
          </button>
          <button class="chip" :class="{ active: filter === 'all' }" @click="setFilter('all')">
            全部 <span class="chip-num">{{ counts.total }}</span>
          </button>
        </div>

        <p class="filter-note">
          「未校验」指当前规则集未覆盖该字段，并非表示没有问题。
        </p>

        <!-- 筛选切换时整块内容淡出淡入；:key="filter" 驱动 Transition。
             外层 .cmp-filter-clip 持久存在，切换时由 setFilter/onFilterEnter
             做高度平滑过渡，新内容插入瞬间高度不跳变 -->
        <div ref="filterClipRef" class="cmp-filter-clip">
        <Transition name="list-swap" mode="out-in" @enter="onFilterEnter">
        <div :key="filter" class="cmp-filtered">
        <template v-if="visible.length">
          <div v-for="g in groups" :key="g.key" class="cmp-group">
            <h3 v-if="showGroupTitle" class="cmp-group-title">
              {{ g.title }} <span class="cmp-group-num">{{ g.list.length }}</span>
            </h3>
            <ul class="cmp-list">
              <li v-for="c in g.list" :id="`cmp-${c.comparison_id}`" :key="c.comparison_id" class="cmp-item">
                <div class="cmp-head">
                  <div class="cmp-title">
                    <!-- 表格与并排对照是平级的两种视图，用分段控件切换，而非展开/收起。
                         控件放最左：视线顺序是 切换方式 → 字段 → 徽章 -->
                    <ViewSwitch
                      :model-value="viewOf(c)"
                      :options="VIEW_OPTIONS"
                      @select="(mode, ev) => setView(c, mode, ev)"
                    />
                    <span class="cmp-label">{{ c.label }}</span>
                    <span class="cmp-key">{{ c.field_key }}</span>
                  </div>
                  <div class="cmp-badges">
                    <StatusBadge :status="severityOf(c.severity)" />
                    <StatusBadge :status="comparisonStatus(c.status)" />
                  </div>
                </div>

                <p v-if="c.note" class="cmp-note">{{ c.note }}</p>

                <!--
                  表格与并排对照面板互为切换：同一信息的两种排布，不同时出现。
                  旧内容直接消失，新内容快速淡入；容器高度由 setView 的 JS 平滑过渡。
                -->
                <div class="cmp-view-body">
                  <Transition name="cmp-swap">
                  <table v-if="viewOf(c) === 'table'" key="table" class="cmp-table">
                    <thead>
                      <tr>
                        <th>来源文件</th>
                        <th>值</th>
                        <th>原文</th>
                        <th>状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="v in c.values" :key="v.file_id" :class="{ 'row-odd': v.field_status !== 'EXTRACTED' }">
                        <td class="cell-file">{{ v.file_name }}</td>
                        <td class="cell-value" data-label="值" :class="{ divergent: isDivergentValue(c, v) }">
                          <template v-if="v.normalized_value !== null && v.normalized_value !== undefined">
                            {{ valueText(v, c) }}
                          </template>
                          <span v-else class="cell-empty">—</span>
                        </td>
                        <td class="cell-raw" data-label="原文">
                          <template v-if="showsRaw(v, c)">{{ v.raw_value }}</template>
                          <!-- raw_value 读不出值时回退到抽取层保留的原文片段，不显示成空白 -->
                          <template v-else-if="rawEvidence(c, v)">{{ rawEvidence(c, v) }}</template>
                          <span v-else class="cell-empty">—</span>
                        </td>
                        <td data-label="状态"><StatusBadge :status="fileStatusOf(v)" /></td>
                      </tr>
                    </tbody>
                  </table>

                  <ComparePane v-else key="pane" :comparison="c" :evidence-index="evidenceIndex" />
                  </Transition>
                </div>

                <div v-if="c.rule_id" class="cmp-foot">依据规则 {{ c.rule_id }}</div>
                <div v-else class="cmp-foot muted">未经规则校验</div>
                <!-- 后端的处理建议（可选，null 时不显示）。建议只辅助人工，不代替比对结论 -->
                <p v-if="c.suggested_action" class="cmp-note">建议：{{ c.suggested_action }}</p>
              </li>
            </ul>
          </div>
        </template>

        <EmptyState
          v-else
          tone="info"
          title="当前筛选下没有条目"
          detail="切到「全部」可查看一致字段。"
        />
        </div>
        </Transition>
        </div>
      </section>

      <section v-else class="card">
        <EmptyState
          tone="info"
          title="后端未返回任何比对结果"
          detail="本次任务没有产出可比对的字段。如需人工确认，请查看「报告」页。"
        />
      </section>
    </template>
  </div>
</template>
