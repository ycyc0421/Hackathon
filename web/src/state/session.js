import { ref } from 'vue'

/**
 * 跨页会话状态：随 vue-router 引入从 App.vue 抽出。
 * 原因：路由守卫（router.js）需要在组件树之外读取 task，
 * 若状态仍藏在 App 组件 setup 里，守卫就拿不到。
 * 各 ref 的语义与初值与迁移前完全一致，App.vue 从这里 import 后
 * 继续用同样的 key provide，页面 inject 一律不改。
 */

/** 当前检查任务。由上传页写入，差异页和报告页读取 */
export const task = ref(null)
export const taskError = ref(null)
export const isRunning = ref(false)

/**
 * 上传页表单状态提升到会话层：文件列表/目的国/备注在切页返回时保留，
 * 与任务状态（task）的生命周期一致——任务还在、输入却丢了，层级不一致。
 * scanWarnings 由文件内容异步检测得出，一并在会话层持有，
 * 否则返回上传页时文件还在、扫描件警告却丢了。
 */
export const uploadFiles = ref([])
export const uploadCountry = ref('DE')
export const uploadNotes = ref('')
export const uploadScanWarnings = ref(new Set())

/**
 * 差异页跨页状态：筛选与每张卡片的 表格/对照 选择在切页返回时保留——
 * 页面内容（task）还在，查看进度却丢了，层级不一致。
 * views 保持 new Map 整体赋值的响应式写法。
 */
export const diffFilter = ref('problems')
export const diffViews = ref(new Map())

/**
 * 评测数据缓存：切页时 EvalPage 会卸载重挂载，缓存留在会话层，
 * 重挂载时直接复用，不再每次切页都重新请求一次。
 */
export const evaluation = ref(null)
export const evaluationLoaded = ref(false)

/**
 * 跨页导航锚点：报告页的条目可以直接跳到差异页对应位置。
 * anchor 经 pendingAnchor 传给目标页（页面随切页重挂载，挂载时消费并清空）。
 */
export const pendingAnchor = ref(null)

/**
 * 首页演示场景卡 → 上传页自动提交的一次性信号。
 * 非 null 表示「用户刚在首页点了某个 mock 场景」：上传页挂载时消费并清空，
 * 随即走一次自动提交（mock 的 createCheck 不依赖真实文件字节）。
 * 一次性消费，避免用户之后手动进上传页时意外触发提交。
 */
export const autoSubmitMock = ref(null)
