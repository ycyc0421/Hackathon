/**
 * PDF 文本层启发式预检测。
 *
 * 背景：后端已验证带文本层的 PDF 可处理；扫描件在未配置识别服务时会解析失败。
 * 用户把扫描件传到后端才报错，体验差。本模块在上传前做一次本地预检测，
 * 命中「疑似无文本层」时给出警告（不阻止提交）。
 *
 * 原理：PDF 的文本层 = 内容流（content stream）里的文本绘制操作。
 * 内容流通常以 FlateDecode 压缩存放在 `stream ... endstream` 段里。
 * 解压后若出现 BT（Begin Text）+ Tj/TJ（文本绘制）操作符，说明这一页在画文字，
 * 即存在文本层。
 *
 * 这是启发式，存在已知误判场景（见 detectPdfTextLayer 注释与 PR 描述），
 * 因此检测结果只用于警告，绝不用于拦截或判定失败。
 */

/** 最多扫描的 stream 段数。文本层通常出现在前几个内容流，扫多了只是浪费 CPU */
const MAX_STREAMS = 20

/** 字节级 ASCII 转字符串，用于在原始字节里找 marker */
function ascii(bytes, start, end) {
  let s = ''
  for (let i = start; i < end; i++) s += String.fromCharCode(bytes[i])
  return s
}

/**
 * 在字节序列里查找子序列（Boyer-Moore 简化版：逐位置比较，文件 ≤20MB 可接受）。
 * @returns {number} 命中的起始下标，未命中返回 -1
 */
function indexOfBytes(bytes, needle, fromIndex = 0) {
  outer: for (let i = fromIndex; i + needle.length <= bytes.length; i++) {
    for (let j = 0; j < needle.length; j++) {
      if (bytes[i + j] !== needle[j]) continue outer
    }
    return i
  }
  return -1
}

const STREAM_MARKER = asciiBytes('stream')
const ENDSTREAM_MARKER = asciiBytes('endstream')

function asciiBytes(s) {
  const out = new Uint8Array(s.length)
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i)
  return out
}

/**
 * 找出文件中前 maxCount 个 `stream\r?\n ... endstream` 段的字节范围。
 * 纯函数，便于 node 测试。
 *
 * 注意：这是字节级扫描，不做 PDF 对象解析。二进制流数据里可能恰好出现
 * `endstream` 字节序列，导致切出的段不正确——调用方解压失败时跳过即可，
 * 启发式容忍这种误切。
 *
 * @param {Uint8Array} bytes 整个 PDF 的字节
 * @param {number} maxCount 最多返回多少段
 * @returns {Array<{start:number,end:number}>} 每段去掉 `stream` 头与换行后的数据区间
 */
export function findStreams(bytes, maxCount = MAX_STREAMS) {
  const ranges = []
  let cursor = 0
  while (ranges.length < maxCount) {
    const s = indexOfBytes(bytes, STREAM_MARKER, cursor)
    if (s === -1) break
    // 按 PDF 规范，`stream` 关键字后紧跟一个 EOL（\r\n 或 \n），数据从 EOL 之后开始
    let dataStart = s + STREAM_MARKER.length
    if (bytes[dataStart] === 0x0d && bytes[dataStart + 1] === 0x0a) dataStart += 2
    else if (bytes[dataStart] === 0x0a) dataStart += 1

    const e = indexOfBytes(bytes, ENDSTREAM_MARKER, dataStart)
    if (e === -1) break
    ranges.push({ start: dataStart, end: e })
    cursor = e + ENDSTREAM_MARKER.length
  }
  return ranges
}

/**
 * 在（已解压的）内容流字节里搜文本绘制操作符。
 * 纯函数，便于 node 测试。
 *
 * 判定：同时出现 `BT`（Begin Text）和 `Tj` 或 `TJ`（两种文本绘制操作符）。
 * 只查 BT 不够——空文本对象 `BT /F1 12 Tf ET` 不画任何字；
 * 只查 Tj 可能撞上别的字节组合（如字体名里的 'Tj'），两个一起查可以压低误报。
 *
 * @param {Uint8Array} bytes 解压后的内容流
 * @returns {boolean}
 */
export function hasTextOperators(bytes) {
  // 内容流是 ASCII 为主的文本，直接按字节转字符串做 includes 判定
  const s = ascii(bytes, 0, bytes.length)
  return s.includes('BT') && (s.includes('Tj') || s.includes('TJ'))
}

/** 检查文件头与加密标记。纯函数，便于 node 测试 */
export function sniffPdfHeader(bytes) {
  const head = ascii(bytes, 0, Math.min(bytes.length, 1024))
  const isPdf = head.startsWith('%PDF')
  // /Encrypt 出现在 trailer 里，可能在文件任意位置，扫全文
  const hasEncrypt = indexOfBytes(bytes, asciiBytes('/Encrypt'), 0) !== -1
  return { isPdf, hasEncrypt }
}

/**
 * 尝试用浏览器内置 DecompressionStream 解压一段（假设是 FlateDecode/zlib 格式）。
 * 解压失败（段不是 deflate、或段被 endstream 误切）返回 null。
 *
 * 注意：按 PDF 规范，endstream 之前还有一个 EOL 不属于数据本身，但字节级扫描
 * 会把这 1~2 个字节包含进段尾。zlib 流自带结束标记，多出的尾部字节会让
 * DecompressionStream 抛 "trailing junk"，所以失败后剥掉段尾 CR/LF 重试一次。
 * （极端情况下压缩数据的最后一个字节恰好是 0x0a，剥掉会导致该段解压失败被跳过；
 * 一份 PDF 通常有多个内容流，丢一段不影响整体判定，这是启发式接受的代价。）
 */
async function tryInflate(bytes) {
  const attempts = [bytes]
  let trimEnd = bytes.length
  while (trimEnd > 0 && (bytes[trimEnd - 1] === 0x0a || bytes[trimEnd - 1] === 0x0d)) trimEnd--
  if (trimEnd < bytes.length) attempts.push(bytes.subarray(0, trimEnd))

  for (const candidate of attempts) {
    try {
      const ds = new DecompressionStream('deflate')
      const stream = new Blob([candidate]).stream().pipeThrough(ds)
      const buf = await new Response(stream).arrayBuffer()
      return new Uint8Array(buf)
    } catch {
      // 该段解不开：误切、非 flate 或尾部仍有杂字节，换下一种切法/跳过
    }
  }
  return null
}

/**
 * 检测一个 PDF 文件是否含文本层。
 *
 * @param {File} file 用户选择的 PDF 文件
 * @returns {Promise<'text'|'no-text'|'unknown'>}
 *   - 'text'    在前若干内容流里找到了文本绘制操作符
 *   - 'no-text' 扫完前 ~20 个 stream 段都没找到 → 疑似扫描件，页面给警告
 *   - 'unknown' 无法判定（非 PDF、加密、浏览器不支持 DecompressionStream、
 *               读文件失败、所有流都无法解压）。页面收到 unknown 一律静默，
 *               不显示任何提示——查不了就查不了，不误报。
 */
export async function detectPdfTextLayer(file) {
  // 老浏览器没有 DecompressionStream 时直接放弃检测
  if (typeof DecompressionStream === 'undefined') return 'unknown'

  let bytes
  try {
    bytes = new Uint8Array(await file.arrayBuffer())
  } catch {
    return 'unknown'
  }

  const { isPdf, hasEncrypt } = sniffPdfHeader(bytes)
  // 非 PDF（用户改了扩展名之类）与加密 PDF 都不在能力范围内，静默降级
  if (!isPdf || hasEncrypt) return 'unknown'

  const streams = findStreams(bytes, MAX_STREAMS)
  let sawInflated = false
  for (const { start, end } of streams) {
    const inflated = await tryInflate(bytes.subarray(start, end))
    if (inflated === null) continue // 该段无法解压（可能误切或非 flate），跳过
    sawInflated = true
    if (hasTextOperators(inflated)) return 'text'
  }

  // 所有段都解不开时多半是内容流用了别的过滤器（如 LZWDecode/ASCII85），
  // 启发式覆盖不到，按 unknown 静默处理，避免对正常文件误报
  if (!sawInflated) return 'unknown'

  return 'no-text'
}
