/**
 * 契约里定义的全部状态枚举的中文文案与样式类。
 *
 * 集中放这里的原因：页面不做 field_key → 中文名的映射（那个由后端给 label），
 * 但状态枚举是前端自己渲染的，必须有一份统一对照表，否则三个页面各写一套。
 *
 * 取值集合来自 docs/schema/check-task.schema.json，改动要同步。
 * 注意：后端已确认任务进行中状态为 PROCESSING（issue #4），schema 的旧写法 RUNNING 已随契约修订更正。
 */

export const TASK_STATUS = {
  PENDING: { text: '排队中', tone: 'muted' },
  PROCESSING: { text: '处理中', tone: 'running' },
  COMPLETED: { text: '已完成', tone: 'ok' },
  PARTIAL: { text: '部分完成', tone: 'warn', hint: '有文件未能处理成功，结果不完整' },
  FAILED: { text: '处理失败', tone: 'bad' },
}

/**
 * 任务分阶段进度。契约里没有显式的 stage 字段（schema 的 TaskStatus 只有五种），
 * 上传页按 task.status 与逐文件 process_status 推断当前处于哪一阶段，
 * 文案集中在这一张表里，与其他状态文案同一出处。
 * 顺序即步骤顺序，页面按 key 在数组里的下标判断"进行到第几步"。
 */
export const TASK_STAGES = [
  { key: 'QUEUED', text: '排队中' },
  { key: 'PARSING', text: '解析文件中' },
  { key: 'COMPARING', text: '交叉比对中' },
  { key: 'FINISHED', text: '已生成结果' },
]

export const PROCESS_STATUS = {
  UPLOADED: { text: '已收到', tone: 'muted' },
  PARSING: { text: '解析中', tone: 'running' },
  EXTRACTED: { text: '已抽取', tone: 'ok' },
  FAILED: { text: '处理失败', tone: 'bad' },
  UNSUPPORTED: { text: '格式不支持', tone: 'warn' },
}

export const FIELD_STATUS = {
  EXTRACTED: { text: '', tone: 'ok' },
  LOW_CONFIDENCE: { text: '请核对', tone: 'warn', hint: '抽取可信度较低' },
  NOT_IN_DOC: { text: '不适用', tone: 'muted', hint: '这份单证按规则本就没有该字段' },
  MISSING_IN_DOC: { text: '文件中未找到', tone: 'warn', hint: '该字段应当存在但未抽取到' },
  UNRECOGNIZED: { text: '未识别', tone: 'bad', hint: '定位到了但读不出值' },
  NORMALIZE_FAILED: { text: '无法归一', tone: 'bad', hint: '读出了值但无法转成可比较的形式' },
}

export const COMPARISON_STATUS = {
  MATCH: { text: '一致', tone: 'ok', isProblem: false },
  CONFLICT: { text: '不一致', tone: 'bad', isProblem: true },
  MISSING_IN_SOME: { text: '部分缺失', tone: 'warn', isProblem: true },
  NOT_CHECKED: { text: '未校验', tone: 'warn', isProblem: true, hint: '当前规则未覆盖，需人工确认' },
  UNRECOGNIZED: { text: '无法比对', tone: 'warn', isProblem: true },
  SINGLE_SOURCE: { text: '仅一份文件', tone: 'muted', isProblem: false },
}

export const RISK_TYPE = {
  MISSING_CERTIFICATE: '可能缺少证书',
  HS_CLASSIFICATION: '归类待复核',
  RULE_UNCOVERED: '规则未覆盖',
  OTHER: '其他提示',
}

export const SEVERITY = {
  INFO: { text: '提示', tone: 'muted' },
  WARNING: { text: '注意', tone: 'warn' },
  ERROR: { text: '问题', tone: 'bad' },
}

export const ERROR_LEVEL = {
  FATAL: { text: '严重', tone: 'bad' },
  ERROR: { text: '错误', tone: 'warn' },
  WARNING: { text: '警告', tone: 'muted' },
}

/**
 * 请求层错误（ApiError.kind）的提示文案。kind 集合见 api/index.js。
 * title 给页面做标题，hint 解释原因与建议动作。
 * UNKNOWN 是兜底：非 ApiError 的异常不该静默吞掉，但也不对客暴露原始报错。
 */
export const API_ERROR_KIND = {
  NETWORK: {
    text: '网络连接失败',
    tone: 'bad',
    title: '上传失败：网络连接异常',
    hint: '前端未收到后端响应。请确认服务已启动、网络与代理配置正确，然后重试。',
  },
  SERVER: {
    text: '服务端错误',
    tone: 'bad',
    title: '服务端处理失败',
    hint: '后端返回了错误。请稍后重试；若持续出现，请把错误信息提供给后端同学排查。',
  },
  PARSE: {
    text: '响应格式异常',
    tone: 'bad',
    title: '后端返回了无法识别的内容',
    hint: '响应不是合法的 JSON，多半是后端或代理出了问题，请联系后端同学排查。',
  },
  TIMEOUT: {
    text: '处理超时',
    tone: 'bad',
    title: '等待超时',
    hint: '等待时间超过上限。后端可能仍在处理，可稍后重试。',
  },
  CANCELED: {
    text: '已取消',
    tone: 'muted',
    title: '操作已取消',
    hint: '',
  },
  UNKNOWN: {
    text: '未知错误',
    tone: 'bad',
    title: '发生了未预期的错误',
    hint: '请刷新页面重试；若持续出现，请联系开发同学排查。',
  },
}

/** 上传相关失败的三类文案：文件过大 / 格式不支持 / 网络失败 */
export const UPLOAD_ERROR_TEXT = {
  FILE_TOO_LARGE: (name, limitMB, actualText) =>
    `文件过大：${name}（${actualText}）超过单文件上限 ${limitMB}MB。请压缩或拆分后重试。`,
  UNSUPPORTED_FORMAT: (names, accept) =>
    `格式不支持：${names}。当前仅支持 ${accept} 格式的单证。`,
  NETWORK: '上传失败：网络连接异常，请检查网络后重试。',
}

/**
 * PDF 文本层预检测的警告文案（只警告、不阻止提交）。
 * 检测是本地启发式（见 src/pdfTextLayer.js），可能误判，所以措辞用「可能」，
 * 并明确告诉用户仍可提交。
 */
export const SCAN_WARNING = {
  /** 文件名旁的行内标记 */
  badge: '⚠ 可能无法识别',
  /** 行内标记的悬浮完整说明 */
  badgeTitle:
    '未检测到此 PDF 的文本层，可能是扫描件。当前后端仅能处理带文本层的 PDF，提交后这份文件可能解析失败。此结果为本地启发式检测，可能有误。',
  /** 汇总提示条 */
  title: '部分文件可能无法解析',
  detail: (n) =>
    `${n} 份文件可能不含文本层（扫描件）。当前后端仅能处理带文本层的 PDF，提交后这些文件可能解析失败；其余文件不受影响，仍可正常提交。`,
}

/** 安全取值：契约新增枚举值时不让页面崩 */
export function lookup(table, key, fallback = '未知') {
  return table[key] ?? { text: fallback, tone: 'muted' }
}
