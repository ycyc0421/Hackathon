<script setup>
/**
 * EDI 原件查看/下载入口（上传列表、文件状态列表、对照面板共用）。
 *
 * 设计约束（issue #40）：
 * - 原件按纯文本展示，完整保留 + : ? ' 与换行；HTML 形似文本用文本插值呈现，
 *   绝不 v-html / document.write / 以 HTML blob 解释——<script>、<b> 都是普通字符；
 * - 不拼 #page 锚、不填页码/bbox/置信度——EDI 没有页码概念；
 * - 只在浏览器内存里确有对应 File 时才提供操作；没有原件时不渲染本组件，
 *   不用 raw_text 拼造整份 EDI（raw_text 只是字段级片段，不是原件）；
 * - 查看/下载都用 File 本身的字节，不重新编码；
 * - objectURL 经共享池管理，关闭查看、切换、卸载都不保留过期预览或下错文件。
 */
import { ref, onBeforeUnmount } from 'vue'
import { createObjectUrlPool, readEdiText, downloadSourceFile } from '../utils/sourceFile.js'
import { EDI_SOURCE_TEXT } from '../api/labels.js'

const props = defineProps({
  /** 浏览器内存里的原始 File（按文件名从 App 层映射取到）。为 null 时不渲染 */
  file: { type: Object, required: true },
})

const open = ref(false)
const text = ref(null)
/** 读取失败的说明：如实提示，不伪造内容，下载原件不受影响 */
const readError = ref(false)

const pool = createObjectUrlPool()

async function toggle() {
  if (open.value) {
    open.value = false
    return
  }
  open.value = true
  if (text.value !== null || readError.value) return
  try {
    text.value = await readEdiText(props.file)
  } catch {
    readError.value = true
  }
}

function download() {
  downloadSourceFile(props.file, pool)
}

onBeforeUnmount(() => pool.dispose())
</script>

<template>
  <div class="edi-source">
    <div class="edi-source-bar">
      <button class="link-btn" @click="toggle">
        {{ open ? EDI_SOURCE_TEXT.collapse : EDI_SOURCE_TEXT.expand }}
      </button>
      <button class="link-btn" @click="download">{{ EDI_SOURCE_TEXT.download }}</button>
    </div>

    <!-- 纯文本预览：白空间保留换行与连续空格；文本插值天然转义 HTML 形似内容 -->
    <div v-if="open" class="edi-source-body">
      <p v-if="readError" class="edi-source-error">{{ EDI_SOURCE_TEXT.readError }}</p>
      <pre v-else-if="text !== null" class="edi-source-text">{{ text }}</pre>
      <p v-else class="edi-source-loading">{{ EDI_SOURCE_TEXT.loading }}</p>
    </div>
  </div>
</template>
