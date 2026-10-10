<script setup>
/**
 * 全局错误边界。
 *
 * 任何一个子组件抛错都不该让整个应用白屏——白屏意味着用户不知道
 * 是文件有问题、网络有问题还是前端有问题，也无法恢复。
 * errorCaptured 拦住子树的异常，渲染成一张带"重新加载"按钮的提示页。
 * 具体错误写进控制台便于排查，不直接展示原始报错给用户。
 */
import { ref, onErrorCaptured } from 'vue'

const crashed = ref(false)
const errorInfo = ref(null)

onErrorCaptured((err) => {
  // 控制台留底：真出问题时这是排查的唯一线索
  console.error('[ErrorBoundary] 子树抛出未捕获异常：', err)
  errorInfo.value = err
  crashed.value = true
  return false // 阻止继续向全局传播，避免二次报错
})

function reload() {
  // 直接整页重载，而不是只清状态——组件树已经崩了，
  // 残留的内部状态不一定还能用，重载是最可靠的恢复路径。
  window.location.reload()
}
</script>

<template>
  <div v-if="crashed" class="error-boundary" role="alert">
    <div class="error-boundary-card">
      <div class="error-boundary-icon" aria-hidden="true">!</div>
      <h1 class="error-boundary-title">页面出现了一些问题</h1>
      <p class="error-boundary-detail">
        界面渲染时发生未预期的错误，已停止显示。重新加载通常可以恢复；
        若反复出现，请把当前操作步骤反馈给开发同学排查。
      </p>
      <button class="btn primary" @click="reload">重新加载</button>
    </div>
  </div>
  <slot v-else />
</template>

<style scoped>
.error-boundary {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6);
  background: var(--surface);
}

.error-boundary-card {
  max-width: 420px;
  padding: var(--space-8);
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
  text-align: center;
}

.error-boundary-icon {
  width: 40px;
  height: 40px;
  margin: 0 auto var(--space-4);
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--danger-bg);
  color: var(--danger);
  font-size: var(--text-xl);
  font-weight: 600;
}

.error-boundary-title {
  margin: 0 0 var(--space-2);
  font-size: var(--text-lg);
  color: var(--text-body);
}

.error-boundary-detail {
  margin: 0 0 var(--space-6);
  font-size: var(--text-sm);
  color: var(--text-muted);
  line-height: var(--leading-relaxed);
}
</style>
