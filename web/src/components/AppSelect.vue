<script>
// attrs（title 等说明性属性）落在触发按钮上，不落到外层容器
export default { inheritAttrs: false }
</script>

<script setup>
/**
 * 自定义下拉选择：按钮 + 下拉浮层，替代原生 <select>（原生下拉
 * 浮层样式不可控，与全站 token 风格不一致）。
 *
 * 交互：
 * - 点击按钮或 Enter/Space/↑/↓ 展开；点击选项选中并收起
 * - 点击组件外部或 Esc 收起；↑/↓ 移动高亮，Enter 选中高亮项
 * - disabled 时不展开、不可聚焦；中途被禁用会收起已展开的浮层
 * - aria：按钮 aria-haspopup="listbox"，浮层 role="listbox"，
 *   选项 role="option"；焦点始终留在按钮上，用 aria-activedescendant 指路
 *
 * 样式在 styles.css 的 .app-select 一组规则里。
 */
import { ref, computed, watch, onBeforeUnmount, nextTick } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  /** [{ value, label }] */
  options: { type: Array, required: true },
  /** 块级模式：宽度 100%，外观对齐 .input（表单场景） */
  block: { type: Boolean, default: false },
  /** 禁用：不接受展开与键盘操作（如提交中的表单字段） */
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'change'])

// 组件可复用，aria-activedescendant 引用的选项 id 需实例间唯一
const instanceId = `app-select-${Math.random().toString(36).slice(2, 10)}`

const root = ref(null)
const listRef = ref(null)
const open = ref(false)
/** 键盘/悬浮高亮项下标；展开时对齐当前选中项 */
const activeIndex = ref(-1)

const selected = computed(() => props.options.find((o) => o.value === props.modelValue))

function optionId(i) {
  return `${instanceId}-opt-${i}`
}

const activeDescendant = computed(() =>
  open.value && activeIndex.value >= 0 ? optionId(activeIndex.value) : undefined
)

function openList() {
  if (props.disabled || open.value) return
  open.value = true
  activeIndex.value = Math.max(
    props.options.findIndex((o) => o.value === props.modelValue),
    0
  )
  document.addEventListener('pointerdown', onOutsidePointer, true)
}

function closeList() {
  if (!open.value) return
  open.value = false
  activeIndex.value = -1
  document.removeEventListener('pointerdown', onOutsidePointer, true)
}

function onOutsidePointer(ev) {
  if (!root.value?.contains(ev.target)) closeList()
}

function choose(o) {
  if (o.value !== props.modelValue) {
    emit('update:modelValue', o.value)
    emit('change', o.value)
  }
  closeList()
}

/** 键盘高亮变化时把选项滚进可视区（选项多的浮层才用得上） */
watch(activeIndex, async (i) => {
  if (i < 0) return
  await nextTick()
  listRef.value?.children[i]?.scrollIntoView({ block: 'nearest' })
})

/** 中途被禁用（如表单开始提交）时收起浮层，不留一个点不动的弹层 */
watch(() => props.disabled, (d) => { if (d) closeList() })

function onKeydown(ev) {
  switch (ev.key) {
    case 'ArrowDown':
    case 'ArrowUp': {
      ev.preventDefault()
      if (!open.value) {
        openList()
        return
      }
      const step = ev.key === 'ArrowDown' ? 1 : -1
      const n = props.options.length
      activeIndex.value = (activeIndex.value + step + n) % n
      break
    }
    case 'Enter':
    case ' ': {
      ev.preventDefault()
      if (!open.value) {
        openList()
      } else if (activeIndex.value >= 0) {
        choose(props.options[activeIndex.value])
      }
      break
    }
    case 'Escape':
      if (open.value) {
        ev.preventDefault()
        closeList()
      }
      break
    case 'Home':
      if (open.value) {
        ev.preventDefault()
        activeIndex.value = 0
      }
      break
    case 'End':
      if (open.value) {
        ev.preventDefault()
        activeIndex.value = props.options.length - 1
      }
      break
  }
}

onBeforeUnmount(() => document.removeEventListener('pointerdown', onOutsidePointer, true))
</script>

<template>
  <div ref="root" class="app-select" :class="{ block, open }">
    <button
      type="button"
      class="app-select-trigger"
      aria-haspopup="listbox"
      :aria-expanded="open"
      :aria-activedescendant="activeDescendant"
      :disabled="disabled"
      v-bind="$attrs"
      @click="open ? closeList() : openList()"
      @keydown="onKeydown"
    >
      <span class="app-select-label">{{ selected?.label ?? '请选择' }}</span>
      <span class="app-select-caret" aria-hidden="true">▾</span>
    </button>
    <!-- 选项与浮层的 click 要 prevent + stop：组件若被包在原生 <label> 里
         （如上传页目的国），点选 <li> 会触发 label 的激活行为，浏览器对
         触发按钮再合成一次 click，刚收起的浮层又被重新展开。
         合成 click 是 label 的默认行为（按祖先链确定，不走冒泡分发），
         仅 stop 拦不住，必须 preventDefault 取消默认行为 -->
    <ul v-if="open" ref="listRef" class="app-select-list" role="listbox" @click.prevent.stop>
      <li
        v-for="(o, i) in options"
        :id="optionId(i)"
        :key="o.value"
        class="app-select-option"
        :class="{ active: i === activeIndex, selected: o.value === modelValue }"
        role="option"
        :aria-selected="o.value === modelValue"
        @pointerenter="activeIndex = i"
        @click.prevent.stop="choose(o)"
      >
        {{ o.label }}
      </li>
    </ul>
  </div>
</template>
