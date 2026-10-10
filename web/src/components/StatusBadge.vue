<script setup>
/**
 * 状态标签。契约里的枚举取值一律通过这个组件渲染，
 * 避免各页面各写一套配色和文案。
 */
import { computed } from 'vue'

const props = defineProps({
  /** labels.js 里任一状态的展示对象：{ text, tone, hint } */
  status: { type: Object, required: true },
  /** 附加在标签后的补充文字，如字段值 */
  suffix: { type: String, default: '' },
})

const hasText = computed(() => Boolean(props.status.text))
</script>

<template>
  <span v-if="hasText" class="badge" :class="`tone-${status.tone}`" :title="status.hint || ''">
    {{ status.text }}<template v-if="suffix">{{ suffix }}</template>
  </span>
</template>
