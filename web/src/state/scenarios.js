/**
 * mock 场景 key → 中文展示名。场景数据本体在 api 层注册表（MOCK_SAMPLES），
 * 这里只存文案。原来放在 App.vue，首页的演示区也要用同一份文案，
 * 抽到会话层共享，避免两处维护同一份映射漂移。
 */
export const SCENARIO_NAMES = {
  'single-item': '单品名 · 有冲突',
  'partial-fail': '单品名 · 部分失败',
  'multi-item': '双品名 · 分组',
  clean: '全部一致',
  'edi-only': 'EDI · 单份报文',
  'edi-mixed': 'EDI · 与 PDF/图片混合',
  'edi-multi-item': 'EDI · 双商品',
  'edi-partial': 'EDI · 部分解析失败',
  'edi-unsupported': 'EDI · 后端不支持',
  'edi-failed': 'EDI · 解析失败',
}

/**
 * 首页演示卡的一句话说明与预期结果走向（tone 与 labels.js 的状态色调同名：
 * ok / warn / bad / muted），说明文字取自各 mock 样例的注释口径。
 */
export const SCENARIO_HINTS = {
  'single-item': { desc: '三份单证件数对不上，演示主路径', tone: 'bad', outcome: '1 处不一致' },
  'partial-fail': { desc: '一份文件处理失败，其余照常比对', tone: 'warn', outcome: '部分完成' },
  'multi-item': { desc: '一票两种商品，按商品分组比对', tone: 'bad', outcome: '分组不一致' },
  clean: { desc: '所有比对条目一致、零风险提示', tone: 'ok', outcome: '全部一致' },
  'edi-only': { desc: '只有一份 EDI 报文，无可交叉项', tone: 'muted', outcome: '仅一份文件' },
  'edi-mixed': { desc: 'EDI 与 PDF、图片混合上传', tone: 'bad', outcome: '数量不一致' },
  'edi-multi-item': { desc: 'EDI 双商品，顺序不同且有缺失', tone: 'bad', outcome: '部分缺失' },
  'edi-partial': { desc: '有效报文与截断报文并存', tone: 'warn', outcome: '部分完成' },
  'edi-unsupported': { desc: '暂不支持该报文类型', tone: 'bad', outcome: '处理失败' },
  'edi-failed': { desc: '报文被截断，解析失败', tone: 'bad', outcome: '处理失败' },
}
