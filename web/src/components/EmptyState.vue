<script setup>
/**
 * 空状态组件。
 *
 * 统一三类场景的占位展示：
 * - info：尚未评测、尚无结果等中性占位
 * - ok：  没有风险提示等正向占位
 * - bad： 加载失败，必须配 onRetry 提供重试
 *
 * 原则：缺数据就占位说明，绝不伪造数值（AGENTS.md 降级原则）。
 * 插图只用 emoji + CSS，不引入图片资源。
 */
defineProps({
  icon: { type: String, default: '📭' },
  title: { type: String, required: true },
  detail: { type: String, default: '' },
  /** info | ok | bad */
  tone: {
    type: String,
    default: 'info',
    validator: (v) => ['info', 'ok', 'bad'].includes(v),
  },
  retryText: { type: String, default: '重试' },
  retrying: { type: Boolean, default: false },
})

const emit = defineEmits(['retry'])
</script>

<template>
  <div class="empty-state" :class="`tone-${tone}`" role="status">
    <div class="empty-state-icon" aria-hidden="true">{{ icon }}</div>
    <div class="empty-state-title">{{ title }}</div>
    <p v-if="detail" class="empty-state-detail">{{ detail }}</p>
    <div v-if="$slots.default" class="empty-state-extra">
      <slot />
    </div>
    <button
      v-if="tone === 'bad'"
      class="btn small empty-state-retry"
      :disabled="retrying"
      @click="emit('retry')"
    >
      {{ retrying ? '重试中…' : retryText }}
    </button>
  </div>
</template>
