/**
 * 契约里定义的全部状态枚举的中文文案与样式类。
 *
 * 集中放这里的原因：页面不做 field_key → 中文名的映射（那个由后端给 label），
 * 但状态枚举是前端自己渲染的，必须有一份统一对照表，否则三个页面各写一套。
 *
 * 取值集合来自 docs/schema/check-task.schema.json，改动要同步。
 */

export const TASK_STATUS = {
  PENDING: { text: '排队中', tone: 'muted' },
  RUNNING: { text: '处理中', tone: 'running' },
  COMPLETED: { text: '已完成', tone: 'ok' },
  PARTIAL: { text: '部分完成', tone: 'warn', hint: '有文件未能处理成功，结果不完整' },
  FAILED: { text: '处理失败', tone: 'bad' },
}

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

/** 安全取值：契约新增枚举值时不让页面崩 */
export function lookup(table, key, fallback = '未知') {
  return table[key] ?? { text: fallback, tone: 'muted' }
}
