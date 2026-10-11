/**
 * 后端统一错误体（{ error: { code, message } }）的错误码 → 用户可读中文文案。
 *
 * 单独成文件而不是并进 labels.js：labels.js 放的是契约枚举的展示文案，
 * 这里的映射只服务于请求失败时的错误提示，跟着后端错误码走、与契约 schema 无关。
 *
 * 文案面向用户，落在页面的错误提示条上（与 hint 并列展示），
 * 所以只写「发生了什么、怎么办」，不重复标题里已有的「服务端处理失败」。
 * 查不到映射时用后端给的 message 兜底——后端写的是面向用户的说明，不是英文 code。
 *
 * 错误码集合以后端实现为准（PR #18），新增错误码在这里补一行即可。
 */
export const BACKEND_ERROR_TEXT = {
  // 400
  INVALID_REQUEST: '请求内容不符合要求，请检查所选文件与目的国后重试。',
  INVALID_DESTINATION_COUNTRY: '暂不支持该目的国，请在下拉列表中选择。',
  INVALID_CURRENCY: '申报币种无法识别，请检查后重试。',
  NO_FILE: '没有收到文件，请至少选择一份单证再提交。',
  // 413
  TOO_MANY_FILES: '一次最多上传 10 份文件，请减少文件数量后重试。',
  FILE_TOO_LARGE: '单个文件超过 20MB 上限，请压缩或拆分后重试。',
  // 404
  TASK_NOT_FOUND: '没有找到这个检查任务，可能已过期，请重新发起检查。',
  // 405
  METHOD_NOT_ALLOWED: '请求方式不被支持，请刷新页面后重试。',
  // 500
  CONTRACT_VIOLATION: '后端返回的数据与约定格式不一致，请联系后端同学排查。',
  INTERNAL_ERROR: '后端处理时出现错误，请稍后重试。',
}

/**
 * 按 ApiError 给出页面上可直接展示的一行说明：
 * 有 code 且命中映射 → 映射文案；否则用后端给的 message；再不行给通用兜底。
 * @param {{ code?: string|null, message?: string }} e
 */
export function backendErrorText(e) {
  if (e?.code && BACKEND_ERROR_TEXT[e.code]) return BACKEND_ERROR_TEXT[e.code]
  return e?.message || '请稍后重试。'
}
