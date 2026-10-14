/**
 * 原件查看/下载的共享工具（纯函数 + 浏览器 API，不依赖组件）。
 *
 * 供上传列表、文件状态列表与对照面板复用同一份原件逻辑：
 * - objectURL 统一创建与回收，避免泄漏或打开过期预览；
 * - EDI 等纯文本原件以 UTF-8 读字节成字符串，绝不重新编码或改写，
 *   展示用文本插值（组件里用 {{ }} 或 textContent），禁用 v-html；
 * - 下载用 <a download> 触发，保留原始字节与文件名。
 */

/** 可交给浏览器内置查看器的 PDF */
const PDF_EXTS = new Set(['PDF'])
/** 能直接 <img> 呈现的位图。矢量格式（svg）不在上传白名单内，不在此列 */
const IMAGE_EXTS = new Set(['PNG', 'JPG', 'JPEG', 'WEBP'])
/** 按纯文本预览的类型：EDI 报文与贸易 JSON 都是文本，严格 UTF-8 解码后原样呈现 */
const TEXT_EXTS = new Set(['EDI', 'JSON'])

/** 取扩展名（大写）。非字符串或没有扩展名时返回空串 */
function extOf(name) {
  if (typeof name !== 'string') return ''
  const parts = name.split('.')
  return parts.length > 1 ? parts.pop().toUpperCase() : ''
}

/**
 * 原件类型判定。**只认扩展名**，与 isEdiName 同一套口径——浏览器对本地
 * 文件给的 MIME 常为空或不可靠，按 MIME 分支会把 PDF 判成 other。
 *
 * - `pdf`   交给浏览器内置 PDF 阅读器（iframe），页码用 `#page` 锚定位
 * - `image` 直接 <img> 呈现
 * - `text`  纯文本（EDI / JSON），严格 UTF-8 解码后按文本呈现
 * - `other` 前端不认识的格式：不猜内容、不做预览，只提供下载
 *
 * @param {string} name 文件名
 * @returns {'pdf'|'image'|'text'|'other'}
 */
export function sourceKind(name) {
  const ext = extOf(name)
  if (PDF_EXTS.has(ext)) return 'pdf'
  if (IMAGE_EXTS.has(ext)) return 'image'
  if (TEXT_EXTS.has(ext)) return 'text'
  return 'other'
}

/** 记录一个组件/页面创建的全部 objectURL，卸载时统一回收 */
export function createObjectUrlPool() {
  const urls = new Set()
  return {
    /**
     * 为 File 创建 objectURL 并登记。返回原始 URL（不含 #page 等锚）。
     * 调用方拼锚（PDF 页码）时用返回值再拼接，回收仍以原始 URL 为准。
     */
    open(file) {
      const url = URL.createObjectURL(file)
      urls.add(url)
      return url
    },
    /**
     * 延迟回收：新窗口加载需要时间，立刻 revoke 会打开空白页。
     * delay 后回收并出池；组件提前卸载时回收兜底由 dispose 负责。
     */
    releaseLater(url, delay = 60_000) {
      const raw = url.split('#')[0]
      setTimeout(() => {
        if (!urls.has(raw)) return
        URL.revokeObjectURL(raw)
        urls.delete(raw)
      }, delay)
    },
    /** 回收池中全部 URL。组件卸载时调用 */
    dispose() {
      for (const url of urls) URL.revokeObjectURL(url)
      urls.clear()
    },
  }
}

/**
 * 读取纯文本原件的字节并严格按 UTF-8 解码。样例为 ASCII / 无 BOM UTF-8；
 * 其他编码由后端声明后再支持（见 #40），解码失败不静默修正，
 * 抛错由调用方降级。只用于文本预览，不回写、不改变上传/下载字节。
 * @returns {Promise<string>} 解码后的文本
 */
export async function readTextSource(file) {
  // 严格解码：非法字节交由组件提示，不能静默替换成看似原文的字符。
  return new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
}

/**
 * 读取 EDI 文本内容。EDI 是纯文本原件的一种，与贸易 JSON 共用同一解码路径，
 * 保留原名以免牵动既有调用点（上传页、文件状态列表、对照面板、node 测试）。
 * @returns {Promise<string>} 解码后的文本
 */
export async function readEdiText(file) {
  return readTextSource(file)
}

/**
 * 触发浏览器下载一份原件。用临时 <a download> + objectURL，
 * 字节就是 File 本身（不重新编码），文件名保留原样。
 * @param {File} file
 * @param {{ open: (f: File) => string, releaseLater: (url: string, d?: number) => void }} pool
 */
export function downloadSourceFile(file, pool) {
  const url = pool.open(file)
  const a = document.createElement('a')
  a.href = url
  a.download = file.name
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  // 下载是同步触发的，但留一拍再回收，确保浏览器已读到字节
  pool.releaseLater(url, 10_000)
}
