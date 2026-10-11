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
import { buildEvidenceIndex, evidenceRawText } from '../utils/evidence.js'
import StatusBadge from '../components/StatusBadge.vue'
import NoticeBar from '../components/NoticeBar.vue'
import SkeletonBlock from '../components/SkeletonBlock.vue'
import EmptyState from '../components/EmptyState.vue'
import ComparePane from '../components/ComparePane.vue'

const task = inject('task')
const isRunning = inject('isRunning')

const filter = ref('problems') // all | problems | conflicts | unchecked

const comparisons = computed(() => task.value?.comparisons ?? [])

const counts = computed(() => {
  const list = comparisons.value
  return {
    total: list.length,
    conflict: list.filter((c) => c.status === 'CONFLICT').length,
    missing: list.filter((c) => c.status === 'MISSING_IN_SOME').length,
    unchecked: list.filter((c) => c.status === 'NOT_CHECKED').length,
    unrecognized: list.filter((c) => c.status === 'UNRECOGNIZED').length,
    match: list.filter((c) => c.status === 'MATCH').length,
    single: list.filter((c) => c.status === 'SINGLE_SOURCE').length,
  }
})

/** 「有问题」= 需要人看一眼的，包括未校验 */
const problemStatuses = ['CONFLICT', 'MISSING_IN_SOME', 'NOT_CHECKED', 'UNRECOGNIZED']

const visible = computed(() => {
  const list = comparisons.value
  switch (filter.value) {
    case 'problems':
      return list.filter((c) => problemStatuses.includes(c.status))
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

/**
 * 每张比对卡片的当前视图：'table'（四行表格，默认）| 'compare'（并排对照）。
 * 两者是同一信息的两种排布、互为切换，不是概要/详情的展开关系，
 * 因此用分段控件切换而不是展开箭头。状态不持久化，切页重挂载后回到表格视图。
 */
const views = ref(new Map())

function viewOf(c) {
  return views.value.get(c.comparison_id) ?? 'table'
}

/**
 * 切换视图时做高度平滑过渡：旧内容直接移除、新内容快速淡入（--duration-fast，
 * 见 .cmp-swap 样式），容器高度由这里的 JS 从旧高度动画到新高度。
 * 不做离场动画、不用 absolute 定位——crossfade 会让父容器高度在过渡中途
 * 坍缩，与高度动画打架，表现为整列抖动。宁可简单稳定。
 * prefers-reduced-motion 下全局 CSS 已把过渡时长压到 0，这里的 JS 自然退化为瞬时。
 */
async function setView(c, mode, ev) {
  if (mode === viewOf(c)) return
  const body = ev?.currentTarget?.closest('.cmp-item')?.querySelector('.cmp-view-body')
  views.value = new Map(views.value).set(c.comparison_id, mode)
  if (!body) return
  const fromH = body.offsetHeight
  body.style.height = `${fromH}px`
  body.style.overflow = 'hidden'
  await nextTick()
  // 测新内容高度：固定高度下 scrollHeight 不小于 clientHeight，内容更矮时
  // 测不准。还原到最终态量真实高度再设回起点；测量与还原在同一帧内
  // 同步完成，不会上屏。
  body.style.cssText = ''
  const toH = body.offsetHeight
  body.style.height = `${fromH}px`
  body.style.overflow = 'hidden'
  if (toH === fromH) {
    // 高度不变不会有 transitionend，直接还原，避免内联样式残留
    body.style.cssText = ''
    return
  }
  body.style.transition = `height var(--duration-base) var(--ease)`
  void body.offsetHeight // 强制 reflow，确立过渡起点
  body.style.height = `${toH}px`
  body.addEventListener(
    'transitionend',
    () => {
      body.style.cssText = ''
    },
    { once: true }
  )
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
 * 目标条目必然在「需关注」集合里（报告页问题条目的过滤条件与 problemStatuses 等价），
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
          <button class="chip" :class="{ active: filter === 'problems' }" @click="filter = 'problems'">
            需关注 <span class="chip-num">{{ counts.conflict + counts.missing + counts.unchecked + counts.unrecognized }}</span>
          </button>
          <button class="chip" :class="{ active: filter === 'conflicts' }" @click="filter = 'conflicts'">
            不一致 <span class="chip-num">{{ counts.conflict }}</span>
          </button>
          <button class="chip" :class="{ active: filter === 'unchecked' }" @click="filter = 'unchecked'">
            未校验 <span class="chip-num">{{ counts.unchecked }}</span>
          </button>
          <button class="chip" :class="{ active: filter === 'all' }" @click="filter = 'all'">
            全部 <span class="chip-num">{{ counts.total }}</span>
          </button>
        </div>

        <p class="filter-note">
          「未校验」指当前规则集未覆盖该字段，并非表示没有问题。
        </p>

        <!-- 筛选切换时整块内容淡出淡入；:key="filter" 驱动 Transition -->
        <Transition name="list-swap" mode="out-in">
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
                    <div class="view-switch" role="group" aria-label="查看方式">
                      <button
                        type="button"
                        :aria-pressed="viewOf(c) === 'table'"
                        @click="setView(c, 'table', $event)"
                      >表格</button>
                      <button
                        type="button"
                        :aria-pressed="viewOf(c) === 'compare'"
                        @click="setView(c, 'compare', $event)"
                      >对照</button>
                    </div>
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
                        <td class="cell-value" :class="{ divergent: isDivergentValue(c, v) }">
                          <template v-if="v.normalized_value !== null && v.normalized_value !== undefined">
                            {{ valueText(v, c) }}
                          </template>
                          <span v-else class="cell-empty">—</span>
                        </td>
                        <td class="cell-raw">
                          <template v-if="showsRaw(v, c)">{{ v.raw_value }}</template>
                          <!-- raw_value 读不出值时回退到抽取层保留的原文片段，不显示成空白 -->
                          <template v-else-if="rawEvidence(c, v)">{{ rawEvidence(c, v) }}</template>
                          <span v-else class="cell-empty">—</span>
                        </td>
                        <td><StatusBadge :status="fileStatusOf(v)" /></td>
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
