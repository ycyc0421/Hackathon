<script setup>
/**
 * 原文预览抽屉：在页面主体右侧起一张纸，就地查看单证原件。
 *
 * 为什么不用 window.open：新标签页把用户从「值 ↔ 原文」的核对动作里带走，
 * 回来还要重新找滚动位置。抽屉与差异页并排，核对是同一屏内的事。
 *
 * 切入方式复用页面层叠的那套语言（DESIGN.md「入口级动画」）：
 * 从右侧整张滑入、时长 `--duration-page`、缓动 `--ease-page`，
 * 与切页的纸张进场同源，读起来是同一套动作而不是新发明的一种。
 * 与切页一致，**不加遮罩压暗桌面**——层次由纸自身的投影与左缘边界表达。
 *
 * 降级原则（与 ComparePane / EdiSourceView 同口径）：
 * - 只有真实拿到 File 对象才渲染，mock 场景没有原件，入口不出现；
 * - page 为 null 不显示页码，也不拼 #page 锚；
 * - 文本原件严格 UTF-8 解码，失败如实提示，不静默替换字符；
 * - 前端不认识的格式不猜内容，只提供下载。
 */
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { SOURCE_PREVIEW_TEXT } from '../api/labels.js'
import {
  createObjectUrlPool,
  downloadSourceFile,
  readTextSource,
  sourceKind,
} from '../utils/sourceFile.js'

const props = defineProps({
  /** 浏览器内存里的原始 File。为 null 表示抽屉关闭 */
  file: { type: Object, default: null },
  /** 命中页码（契约的 values[].page），null 时不显示也不拼锚点 */
  page: { type: Number, default: null },
})

const emit = defineEmits(['close'])

/** 抽屉是否打开：由 file 是否存在决定，父组件置 null 即关闭 */
const open = computed(() => !!props.file)

const kind = computed(() => (props.file ? sourceKind(props.file.name) : 'other'))

/** 文本原件的解码结果；null 表示尚未读出 */
const text = ref(null)
/** 文本解码失败：如实提示，不显示半截内容 */
const textError = ref(false)

const pool = createObjectUrlPool()
/** 当前 PDF/图片的 objectURL，随文件切换重建、随抽屉关闭回收。
 *  走独立变量而不进池：池管的是下载这类"发出去就不管"的 URL，
 *  预览 URL 的生命周期完全由抽屉自己掌握。 */
const objectUrl = ref('')
/** 关闭按钮：抽屉打开后焦点移到这里，键盘用户不必 Tab 找出口 */
const closeRef = ref(null)
/** 文本读取的序号：快速连续切换文件时，晚到的旧读取结果作废 */
let textLoadSeq = 0

/** PDF 拼 #page 锚交给浏览器内置阅读器跳页；图片与文本不拼 */
const frameSrc = computed(() => {
  if (!objectUrl.value) return ''
  if (kind.value === 'pdf' && props.page != null) return `${objectUrl.value}#page=${props.page}`
  return objectUrl.value
})

function releaseUrl() {
  if (objectUrl.value) {
    URL.revokeObjectURL(objectUrl.value)
    objectUrl.value = ''
  }
}

async function load(file) {
  const seq = ++textLoadSeq
  text.value = null
  textError.value = false
  releaseUrl()
  if (!file) return
  const k = sourceKind(file.name)
  if (k === 'pdf' || k === 'image') {
    objectUrl.value = URL.createObjectURL(file)
    return
  }
  if (k === 'text') {
    try {
      const decoded = await readTextSource(file)
      if (seq !== textLoadSeq) return // 期间又切了文件，结果作废
      text.value = decoded
    } catch {
      if (seq !== textLoadSeq) return
      textError.value = true
    }
  }
}

watch(
  () => props.file,
  async (file) => {
    await load(file)
    if (!file) return
    // 打开后把焦点交给关闭按钮：键盘用户进来就有明确出口
    await nextTick()
    closeRef.value?.focus()
  },
  { immediate: true }
)

/** Esc 关闭。挂在 window 上：焦点进了 iframe（浏览器内置 PDF 阅读器）后，
 *  元素自身收不到按键。本组件全站同时只有一个实例，不与兄弟实例抢键。 */
function onWindowKeydown(e) {
  if (e.key === 'Escape') emit('close')
}

watch(
  open,
  (isOpen) => {
    if (isOpen) window.addEventListener('keydown', onWindowKeydown)
    else window.removeEventListener('keydown', onWindowKeydown)
  },
  { immediate: true }
)

function download() {
  if (props.file) downloadSourceFile(props.file, pool)
}

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onWindowKeydown)
  releaseUrl()
  pool.dispose()
})
</script>

<template>
  <!--
    必须 Teleport 到 body：抽屉用 position: fixed，而切页过渡会给 .page-inner
    加 transform，transform 的祖先会成为 fixed 的包含块，抽屉会被锁在纸张内
    而不是贴在视口右侧。挂到 body 下才真正相对视口定位。
  -->
  <Teleport to="body">
    <Transition name="source-drawer">
      <aside
        v-if="open"
        class="source-drawer"
        role="dialog"
        aria-modal="false"
        :aria-label="`原文预览：${file.name}`"
      >
        <header class="source-drawer-head">
          <div class="source-drawer-title">
            <span class="source-drawer-name" :title="file.name">{{ file.name }}</span>
            <span v-if="page != null && kind === 'pdf'" class="source-drawer-page">
              {{ SOURCE_PREVIEW_TEXT.page(page) }}
            </span>
          </div>
          <div class="source-drawer-actions">
            <button class="link-btn" @click="download">{{ SOURCE_PREVIEW_TEXT.download }}</button>
            <button
              ref="closeRef"
              type="button"
              class="source-drawer-close"
              :aria-label="SOURCE_PREVIEW_TEXT.close"
              :title="SOURCE_PREVIEW_TEXT.closeTitle"
              @click="emit('close')"
            >
              <span aria-hidden="true">✕</span>
            </button>
          </div>
        </header>

        <div class="source-drawer-body">
          <!-- PDF：交给浏览器内置阅读器，页码靠 #page 锚跳转 -->
          <iframe
            v-if="kind === 'pdf' && frameSrc"
            class="source-drawer-frame"
            :src="frameSrc"
            :title="file.name"
          />

          <!-- 图片：直接呈现原始字节 -->
          <img v-else-if="kind === 'image' && frameSrc" class="source-drawer-image" :src="frameSrc" :alt="file.name" />

          <!-- 纯文本（EDI / JSON）：严格解码后原样呈现，文本插值天然转义 HTML 形似内容 -->
          <pre v-else-if="kind === 'text' && text !== null" class="source-drawer-text">{{ text }}</pre>

          <p v-else-if="kind === 'text' && textError" class="source-drawer-note">
            {{ SOURCE_PREVIEW_TEXT.textError }}
          </p>
          <p v-else-if="kind === 'text'" class="source-drawer-note">{{ SOURCE_PREVIEW_TEXT.loading }}</p>

          <!-- 不认识的格式：不猜内容 -->
          <p v-else class="source-drawer-note">{{ SOURCE_PREVIEW_TEXT.unsupported }}</p>
        </div>
      </aside>
    </Transition>
  </Teleport>
</template>
