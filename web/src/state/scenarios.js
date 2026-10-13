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
