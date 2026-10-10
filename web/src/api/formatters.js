/**
 * 展示层的格式化。
 *
 * 原则：不做业务判断，只按 value_type 和 unit 决定怎么显示。
 * 归一化是后端的事，这里拿到的 normalized_value 已经是可比较的值。
 */

import { lookup, SEVERITY, TASK_STATUS, PROCESS_STATUS, FIELD_STATUS, COMPARISON_STATUS, RISK_TYPE, ERROR_LEVEL } from './labels.js'

/**
 * 按 value_type 渲染归一值。
 * 返回 { main, sub }：main 是主显示，sub 是可选的次要信息（如币种）。
 */
export function formatValue(value, valueType, unit) {
  if (value === null || value === undefined) return { main: '—', sub: null }

  switch (valueType) {
    case 'MONEY': {
      const n = typeof value === 'number' ? value.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) : String(value)
      return { main: n, sub: unit ?? null }
    }
    case 'NUMBER': {
      const n = typeof value === 'number' ? value.toLocaleString('zh-CN') : String(value)
      return { main: n, sub: unit ?? null }
    }
    case 'DATE':
    case 'CODE':
    case 'STRING':
    default:
      return { main: String(value), sub: unit ?? null }
  }
}

/** ISO 时间转本地可读。不引日期库，格式化程度到这里够用 */
export function formatTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** 耗时秒数，用于任务已完成时显示 */
export function formatDuration(startIso, endIso) {
  if (!startIso || !endIso) return null
  const ms = new Date(endIso) - new Date(startIso)
  if (Number.isNaN(ms) || ms < 0) return null
  return `${(ms / 1000).toFixed(1)} 秒`
}

export function confidenceText(c) {
  if (c === null || c === undefined) return null
  return `可信度 ${(c * 100).toFixed(0)}%`
}

// —— 以下为状态取值 → 展示对象的薄封装，避免各页面重复 lookup ——

export const taskStatus = (v) => lookup(TASK_STATUS, v)
export const processStatus = (v) => lookup(PROCESS_STATUS, v)
export const fieldStatus = (v) => lookup(FIELD_STATUS, v)
export const comparisonStatus = (v) => lookup(COMPARISON_STATUS, v)
export const severity = (v) => lookup(SEVERITY, v, '提示')
export const riskType = (v) => RISK_TYPE[v] ?? '其他提示'
export const errorLevel = (v) => lookup(ERROR_LEVEL, v)
