/**
 * 契约里定义的全部状态枚举的中文文案与样式类。
 *
 * 集中放这里的原因：页面不做 field_key → 中文名的映射（那个由后端给 label），
 * 但状态枚举是前端自己渲染的，必须有一份统一对照表，否则三个页面各写一套。
 *
 * 取值集合来自 docs/schema/check-task.schema.json，改动要同步。
 * 报告契约 v2 独有的枚举（核实状态、局限说明等）来自
 * docs/schema/report-content.schema.json，单独成组放在文件末尾。
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

/**
 * 单证类型。此前报告页直接输出 COMMERCIAL_INVOICE 这类契约枚举当展示文案
 * （issue #51 第 3 点），导出件又把它原样带进用户报告，所以在这里补一张表。
 * 查不到时 lookup 兜底为「未知」，不把英文枚举甩给用户。
 */
export const DOC_TYPE = {
  COMMERCIAL_INVOICE: { text: '商业发票', tone: 'muted' },
  PACKING_LIST: { text: '装箱单', tone: 'muted' },
  BILL_OF_LADING: { text: '提单', tone: 'muted' },
  CUSTOMS_DECLARATION: { text: '报关单', tone: 'muted' },
  CERTIFICATE_OF_ORIGIN: { text: '原产地证', tone: 'muted' },
  INSURANCE_POLICY: { text: '保险单', tone: 'muted' },
  OTHER: { text: '其他单证', tone: 'muted' },
}

/**
 * 行组对齐状态（report v2 的 items[].alignment_status）。
 * PARTIAL / UNALIGNED 表示商品行没能完整对上，比对覆盖不完整，
 * 不能读成"没问题"，所以带 hint 说明。
 */
export const ALIGNMENT_STATUS = {
  ALIGNED: { text: '已对齐', tone: 'ok' },
  PARTIAL: { text: '部分对齐', tone: 'warn', hint: '该行组只在部分文件中找到对应行，比对覆盖不完整' },
  UNALIGNED: { text: '未对齐', tone: 'warn', hint: '该行组未能在其他文件中找到对应行，仅作为单文件证据' },
}

/**
 * 行组对齐依据（items[].alignment_basis）。对齐依据是机器判断的线索，
 * 只作说明用途，不代表比对结论。
 */
export const ALIGNMENT_BASIS = {
  ITEM_CODE: '按货号对齐',
  DESCRIPTION: '按品名描述对齐',
  POSITION: '按行号位置对齐',
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

/* ---------- 报告契约 v2（docs/schema/report-content.schema.json）----------
   以下枚举只出现在报告内容里，不在 CheckTask 契约中。取值同样来自
   docs/schema/report-content.schema.json，改动要同步。 */

/**
 * 规则核实状态（risk.rule_context.verification_status 与
 * provenance.rule_verification_status）。
 *
 * 三个取值**都不是 VERIFIED**：契约里根本没有"已核实"这一档。
 * 所以文案不能写成"已核实"，也不能因为缺省而让读者以为默认通过——
 * 未核实、未检查、未知都必须各自显示出来。
 */
export const VERIFICATION_STATUS = {
  UNVERIFIED: { text: '未经人工核实', tone: 'warn', hint: '规则适用条件尚需人工核实，提示不代表合规结论' },
  NOT_CHECKED: { text: '未校验', tone: 'warn', hint: '没有对应的规则编号，未做规则校验' },
  UNKNOWN: { text: '核实状态未知', tone: 'muted', hint: '没有足够信息判断该规则是否经过核实' },
}

/** 历史规则版本的记录状态（provenance.execution_version_status） */
export const EXECUTION_VERSION_STATUS = {
  /** 原任务没有留下历史版本记录——必须如实说不知道，不能用当前版本顶替 */
  UNKNOWN: '原任务未记录当时使用的规则版本',
  RECORDED_IN_CORRECTION: '来自最近一次修正的审计记录',
}

/**
 * 报告局限说明（limitations[]）。后端给的是固定语义代码，
 * 由前端统一组织成中文，不逐条当正文堆叠（issue #51 第 6 点）。
 */
export const LIMITATION_TEXT = {
  PROCESSING_IS_NOT_COMPLIANCE: '处理完成只表示流程走完，不代表合规通过。',
  UNKNOWN_HISTORY_IS_NOT_CURRENT_VERSION: '历史规则版本缺失时按未知处理，不用当前版本回填。',
  UNVERIFIED_RULES_REQUIRE_REVIEW: '规则适用条件未经人工核实，风险提示需要人工复核。',
}

/**
 * 来源监测状态（provenance.sources[].status）。
 *
 * 注意 `NOT_CHECKED` 在这里的含义与比对状态、核实状态都不同：它说的是
 * "这个来源的内容有没有去查过更新"，不是"这条规则校验过没有"。
 * 所以文案要带上"来源"二字，避免读者把它和别处的"未校验"混为一谈。
 */
export const SOURCE_STATUS = {
  NOT_CHECKED: { text: '来源更新未检查', tone: 'muted', hint: '未配置来源监测，仅展示目录，不代表没有变化' },
  PENDING_REVIEW: { text: '来源有变更待复核', tone: 'warn', hint: '来源内容变化不等于法规修订，不会自动替换运行规则' },
  UNCHANGED: { text: '来源未变化', tone: 'ok' },
  CHANGED: { text: '来源内容已变化', tone: 'warn' },
}

/**
 * 来源适用性复核状态（provenance.sources[].review_status）。
 * 所有取值都表示"还没确认这条来源是否适用于本票"，没有"已适用"这一档。
 */
export const SOURCE_REVIEW_STATUS = {
  APPLICABILITY_REVIEW_REQUIRED: { text: '适用性待复核', tone: 'warn', hint: '该来源是否适用于本票尚未确认' },
  REVIEWED: { text: '适用性已复核', tone: 'ok' },
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
  /** 同名文件会让「查看原文」的本地映射互相覆盖，必须阻断而不是静默接受 */
  DUPLICATE_NAME: (names) =>
    `同名文件无法区分原文，请重命名后再添加：${names}。`,
  NETWORK: '上传失败：网络连接异常，请检查网络后重试。',
}

/**
 * EDI 能力说明（issue #40）。
 * 前端接受 .edi 只表示允许提交原件，不代表后端已能解析；真实模式如实展示
 * 后端不支持或失败的原因，不虚构能力，也不把示例数据切入真实模式。
 * 解析范围（报文类型/版本/编码）待后端与数据侧确认，文案不替其声明支持。
 */
export const EDI_CAPABILITY = {
  /** 上传入口的支持说明后缀，接在通用格式列表之后 */
  hint: '.edi 为 EDIFACT 发票报文；当前后端解析能力以实际结果为准，不支持时会如实提示。',
  /** 真实模式下提交 EDI 前的能力提示 */
  realNote: 'EDI 解析依赖后端能力：若后端暂不支持，任务会如实标记为失败/不支持，不会当作通过。',
}

/** EDI 原件查看/下载的按钮与状态文案 */
export const EDI_SOURCE_TEXT = {
  expand: '查看原文',
  collapse: '收起原文',
  download: '下载原件',
  loading: '读取原件…',
  readError: '原件不是可解码的 UTF-8 文本，无法预览。可下载原件查看；未对内容做任何修改。',
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
    '未检测到此 PDF 的文本层，可能是扫描件，识别依赖后端 OCR 配置与处理结果。此结果为本地启发式检测，可能有误，仍可提交。',
  /** 汇总提示条 */
  title: '部分文件可能无法解析',
  detail: (n) =>
    `${n} 份文件可能不含文本层（扫描件），识别依赖后端 OCR 配置与处理结果，仍可正常提交；实际失败原因会按文件展示。`,
}

/** 安全取值：契约新增枚举值时不让页面崩 */
export function lookup(table, key, fallback = '未知') {
  return table[key] ?? { text: fallback, tone: 'muted' }
}
