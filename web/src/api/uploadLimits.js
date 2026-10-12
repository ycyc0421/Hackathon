/**
 * 上传文件集合的前端校验。
 *
 * 单独成模块（不依赖 config.js）的原因：canSubmit 与 submit 都要以
 * 当前文件集合实时跑 validateFiles 为准，这段逻辑必须能在 node 里单测。
 */

/**
 * 上传前的前端校验。上限来自契约第四节第 11 项的当前处理方式，需后端侧确认。
 *
 * accept 是唯一白名单：选择器 accept 属性、拖放入口校验、界面支持说明都从它派生，
 * 不接受 .txt——直到后端明确 EDI 的识别约定（issue #40）。扩展名不区分大小写，
 * .edi 与 .EDI 均可，但不靠 MIME 判断（浏览器常给空或不可靠的 MIME）。
 */
export const UPLOAD_LIMITS = {
  maxFiles: 10,
  maxFileSizeMB: 20,
  accept: '.pdf,.png,.jpg,.jpeg,.webp,.edi',
}

/**
 * 按扩展名识别 EDI 文件（大小写一致）。用于原文查看/下载的分支判定，
 * 与后端把它标为 EDI / OTHER / UNSUPPORTED 无关——前端只认本地扩展名。
 * 不要用文件内容猜测（invoice.txt 内容像 EDI 也不接受）。
 */
export function isEdiName(name) {
  return typeof name === 'string' && name.split('.').pop()?.toUpperCase() === 'EDI'
}

/**
 * 阻塞性限制：不满足则禁止提交。
 * 扫描件预检测警告不在这里——它是非阻塞提示，见 UploadPage 的 scanWarnings。
 */
export function validateFiles(fileList) {
  const errors = []
  const files = Array.from(fileList)

  if (files.length === 0) errors.push('请至少选择一份文件')
  if (files.length > UPLOAD_LIMITS.maxFiles) {
    errors.push(`一次最多 ${UPLOAD_LIMITS.maxFiles} 份文件，当前 ${files.length} 份`)
  }

  for (const f of files) {
    const mb = f.size / 1024 / 1024
    if (mb > UPLOAD_LIMITS.maxFileSizeMB) {
      errors.push(`${f.name} 超过 ${UPLOAD_LIMITS.maxFileSizeMB}MB（${mb.toFixed(1)}MB）`)
    }
  }

  return errors
}

/**
 * 按文件名阻断同名歧义。
 *
 * 「查看原文」按 file.name 关联浏览器内存里的 File 对象，契约没有给出
 * file_id 与本地 File 的稳定映射；同名文件会让映射互相覆盖、打开错原文。
 * 在契约给出可靠身份之前，前端按文件名拒绝同名（不看大小——同名即歧义）。
 *
 * @returns {{ fresh: File[], duplicateNames: string[] }}
 */
export function splitByName(existing, incoming) {
  const seen = new Set(existing.map((f) => f.name))
  const fresh = []
  const duplicateNames = []
  for (const f of incoming) {
    if (seen.has(f.name)) {
      duplicateNames.push(f.name)
    } else {
      seen.add(f.name)
      fresh.push(f)
    }
  }
  return { fresh, duplicateNames }
}
