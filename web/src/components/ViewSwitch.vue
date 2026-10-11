<script setup>
/**
 * 分段控件：两个平级选项，选中态由按钮背后的 pill 指示器表达。
 * 切换时 pill 以 transform + width 平滑滑动（--duration-fast），
 * 不是背景色瞬变；选项宽度不同时 pill 宽度跟随实测值。
 * 样式在 styles.css 的 .view-switch 一组规则里。
 *
 * 首帧静默定位：挂载后首次 measure 不带过渡——pill 初始样式含
 * transition:none，首次定位在双 rAF 里完成（此时 transition 仍禁用，
 * 跳变不上屏），之后才恢复过渡供后续切换使用。否则每次挂载 pill
 * 都会从第一个选项位置「滑到」实际选中项（用户感知为按钮闪动）。
 */
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'

const props = defineProps({
  modelValue: { type: String, required: true },
  /** [{ value, label }] */
  options: { type: Array, required: true },
  ariaLabel: { type: String, default: '查看方式' },
})
const emit = defineEmits(['select'])

const root = ref(null)
const buttons = ref([])
// 初始 transition:none：首次定位必须静默完成，见文件头注释
const pillStyle = ref({ opacity: '0', transition: 'none' })

/** 首次定位完成前禁用过渡；定位后由双 rAF 恢复 */
let firstMeasurePending = true

/** 按当前选中按钮的实测位置/宽度安放 pill；测不到（未挂载）时隐藏 */
function measure() {
  const i = props.options.findIndex((o) => o.value === props.modelValue)
  const el = buttons.value[i]
  if (!el) {
    pillStyle.value = firstMeasurePending
      ? { opacity: '0', transition: 'none' }
      : { opacity: '0' }
    return
  }
  // offsetLeft/offsetWidth 相对容器（position:relative），已含容器内边距
  pillStyle.value = {
    opacity: '1',
    width: `${el.offsetWidth}px`,
    transform: `translateX(${el.offsetLeft}px)`,
    ...(firstMeasurePending ? { transition: 'none' } : {}),
  }
  if (firstMeasurePending) {
    // 首次定位静默完成：transition 保持 none，双 rAF 后（首帧已上屏）再恢复，
    // 避免从初始位置到实际选中项之间产生可见滑动
    firstMeasurePending = false
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const { transition, ...rest } = pillStyle.value
        pillStyle.value = rest
      })
    })
  }
}

function pick(o, ev) {
  if (o.value === props.modelValue) return
  // emit 在 click 分发过程中同步执行：父级处理函数里 ev.currentTarget
  // 仍指向被点击的按钮，可沿 DOM 找到所在卡片做高度过渡测量
  emit('select', o.value, ev)
}

watch(
  () => props.modelValue,
  () => nextTick(measure)
)

let resizeObserver = null
onMounted(() => {
  measure()
  if (root.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(measure)
    resizeObserver.observe(root.value)
  }
})
onBeforeUnmount(() => resizeObserver?.disconnect())
</script>

<template>
  <div ref="root" class="view-switch" role="group" :aria-label="ariaLabel">
    <span class="view-switch-pill" :style="pillStyle" aria-hidden="true" />
    <button
      v-for="(o, i) in options"
      :key="o.value"
      :ref="(el) => (buttons[i] = el)"
      type="button"
      :aria-pressed="modelValue === o.value"
      @click="pick(o, $event)"
    >
      {{ o.label }}
    </button>
  </div>
</template>
