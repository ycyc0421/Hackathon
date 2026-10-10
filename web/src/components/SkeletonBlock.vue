<script setup>
/**
 * 骨架屏基础块：一个带闪烁动画的占位矩形。
 *
 * 颜色、圆角、动画时长全部来自 design-tokens.css 的变量。
 * prefers-reduced-motion 的降帧由 token 文件的全局规则统一处理，
 * 这里不重复声明。
 */
defineProps({
  /** 宽度，任意合法 CSS 长度 */
  width: { type: String, default: '100%' },
  /** 高度，任意合法 CSS 长度 */
  height: { type: String, default: '14px' },
  /** 圆角档位：sm 用于行内文本块，md 用于卡片级块 */
  radius: {
    type: String,
    default: 'sm',
    validator: (v) => ['sm', 'md', 'lg'].includes(v),
  },
})
</script>

<template>
  <div
    class="skeleton-block"
    :style="{ width, height, borderRadius: `var(--radius-${radius})` }"
    aria-hidden="true"
  />
</template>

<style scoped>
.skeleton-block {
  background: linear-gradient(
    90deg,
    var(--gray-100) 0%,
    var(--gray-200) 50%,
    var(--gray-100) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer var(--duration-slow) var(--ease) infinite alternate;
}

@keyframes skeleton-shimmer {
  from {
    background-position: 100% 0;
  }
  to {
    background-position: -100% 0;
  }
}
</style>
