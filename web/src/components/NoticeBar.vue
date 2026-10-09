<script setup>
/**
 * 提示条。用于页面顶部的汇总提示：
 * 「本次检查未包含全部文件」「尚未评测」这类必须让用户看到的信息。
 *
 * 存在的意义：契约里 PARTIAL、NOT_CHECKED、FAILED 这些状态
 * 容易被实现成静默忽略，这个组件把它们强制显示出来。
 */
defineProps({
  tone: {
    type: String,
    default: 'info',
    validator: (v) => ['info', 'warn', 'bad', 'ok'].includes(v),
  },
  title: { type: String, required: true },
  detail: { type: String, default: '' },
})
</script>

<template>
  <div class="notice" :class="`tone-${tone}`">
    <div class="notice-title">{{ title }}</div>
    <div v-if="detail" class="notice-detail">{{ detail }}</div>
    <slot />
  </div>
</template>
