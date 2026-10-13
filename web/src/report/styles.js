/**
 * 导出报告的样式（自包含字符串，随 HTML 一起下载）。
 *
 * 为什么内联而不是引用 design-tokens.css：导出的 HTML 是一个**独立的文件**，
 * 用户会把它存下来、发给别人、或直接打印成 PDF。它不能依赖 web 应用的样式表，
 * 也不能依赖构建产物——文件一旦离开应用就必须自己站得住。
 *
 * 视觉语言照 `web/DESIGN.md` 与 `web/src/design-tokens.css`（PR #50 为准）：
 * 桌面 → 纸 → 下沉三层表面，层级由表面亮度差、圆角梯度与极轻投影建立，
 * 边框只作保底。取值直接照抄 token，改 token 时这里要同步。
 *
 * 三处刻意的取舍：
 *
 * 1. **只做浅色**。导出件的主要出口是打印成 PDF，纸面就是白底；跟随系统暗色
 *    会让"屏幕上看是深色、打出来是白底"变成两套观感。桌面端应用才有暗色主题。
 * 2. **不做任何动效**。这是文档不是界面，`DESIGN.md` 的动画纪律（功能反馈动画）
 *    在这里没有适用对象——静态、可打印、抽帧即所见。
 * 3. **不用相对颜色语法**（`oklch(from …)`）。语义色底色写成"同色相 + 低透明度"
 *    的字面值，与 token 里的相对写法在白纸上等效，但不依赖较新的浏览器特性。
 *
 * 颜色永远不是唯一的信息载体（`DESIGN.md` 原则 2）：每个带语义色的元素
 * 同时有文字或图标，黑白打印也读得出来。
 */

export const REPORT_CSS = `
:root {
  color-scheme: light;

  /* 中性灰阶（冷灰，微带蓝调） */
  --gray-50: oklch(98% 0.002 250);
  --gray-100: oklch(96% 0.004 250);
  --gray-200: oklch(90% 0.006 250);
  --gray-300: oklch(82% 0.008 250);
  --gray-400: oklch(70% 0.01 250);
  --gray-600: oklch(45% 0.012 250);
  --gray-900: oklch(18% 0.006 250);

  --blue-500: oklch(52% 0.14 240);
  --blue-600: oklch(45% 0.14 240);

  /* 语义色。底色是同色相 + 低透明度，压在白纸上即浅色块 */
  --success: oklch(56% 0.15 148);
  --success-bg: oklch(56% 0.15 148 / 0.1);
  --warning: oklch(66% 0.16 62);
  --warning-bg: oklch(66% 0.16 62 / 0.12);
  --danger: oklch(56% 0.19 25);
  --danger-bg: oklch(56% 0.19 25 / 0.1);
  --info: oklch(60% 0.12 230);
  --info-bg: oklch(60% 0.12 230 / 0.1);

  /* 三层表面 */
  --surface-desk: oklch(96.6% 0.005 250);
  --surface-raised: #fff;
  --surface-sunken: oklch(97.2% 0.004 250);
  --border: oklch(92% 0.006 250);
  --border-strong: oklch(86% 0.008 250);
  --desk-dot: oklch(45% 0.02 250 / 0.042);

  --text-body: var(--gray-900);
  --text-muted: var(--gray-600);
  --text-disabled: var(--gray-400);

  --space-1: 4px;  --space-2: 8px;  --space-3: 12px; --space-4: 16px;
  --space-5: 20px; --space-6: 24px; --space-8: 32px; --space-10: 40px;

  --radius-sm: 5px; --radius-md: 7px; --radius-lg: 9px; --radius-pill: 999px;

  --shadow-sm: 0 1px 2px oklch(30% 0.02 250 / 0.04),
               0 2px 6px oklch(30% 0.02 250 / 0.05);
  --shadow-paper: 0 1px 1px oklch(30% 0.02 250 / 0.03),
                  0 12px 32px -8px oklch(30% 0.02 250 / 0.10);

  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI",
               "Noto Sans SC", "Microsoft YaHei", sans-serif;
  --font-mono: "JetBrains Mono", "JetBrainsMono Nerd Font", "SF Mono", Consolas,
               "Liberation Mono", monospace;

  --text-2xs: 10px; --text-xs: 12px; --text-13: 13px; --text-sm: 14px;
  --text-base: 16px; --text-lg: 18px; --text-xl: 20px; --text-2xl: 24px;
  --text-3xl: 30px;

  --leading-tight: 1.25; --leading-normal: 1.5; --leading-relaxed: 1.75;
}

/* 状态色承载语义，打印时必须保留（否则"问题/注意"全变成一样的灰） */
html { print-color-adjust: exact; -webkit-print-color-adjust: exact; }

* { box-sizing: border-box; }

body {
  margin: 0;
  padding: var(--space-8) var(--space-4) var(--space-10);
  background: var(--surface-desk);
  color: var(--text-body);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* 桌面点阵：与应用的桌面同源，导出件不显得是"另一套东西"。
   只在屏幕上出现，打印时移除（见 @media print）。 */
body::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background-image: radial-gradient(var(--desk-dot) 1px, transparent 1px);
  background-size: 24px 24px;
  mask-image: radial-gradient(ellipse 120% 80% at 50% 0%, #000 30%, transparent 78%);
  -webkit-mask-image: radial-gradient(ellipse 120% 80% at 50% 0%, #000 30%, transparent 78%);
}

.report {
  position: relative;
  z-index: 1;
  max-width: 880px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* ---------- 纸：内容卡 ---------- */

.card {
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-5) var(--space-6);
}

.card-title {
  margin: 0 0 var(--space-1);
  font-size: var(--text-lg);
  font-weight: 600;
}

.card-sub {
  margin: 0 0 var(--space-4);
  color: var(--text-muted);
  font-size: var(--text-sm);
}

.title-num {
  color: var(--text-muted);
  font-weight: 400;
}

/* ---------- 报告头：状态色带 + 标题 + 结论 ---------- */

.report-head {
  position: relative;
  overflow: hidden;
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-paper);
  padding: calc(var(--space-6) + 4px) var(--space-6) var(--space-6);
}

/* 顶部 4px 色带：整页状态的第一眼信号，颜色与结论文案同源推导 */
.report-head::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 4px;
  background: var(--gray-300);
}

.report-head.tone-bad::before { background: var(--danger); }
.report-head.tone-warn::before { background: var(--warning); }
.report-head.tone-ok::before { background: var(--success); }

.report-kicker {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.report-title {
  margin: 0;
  font-size: var(--text-2xl);
  font-weight: 600;
  line-height: var(--leading-tight);
}

.report-sub {
  margin: var(--space-1) 0 0;
  color: var(--text-muted);
  font-size: var(--text-sm);
}

/* 结论是全页最重要的一句话，先于统计数字出现 */
.report-conclusion {
  margin: var(--space-4) 0 var(--space-5);
  padding: var(--space-4) var(--space-5);
  border: 1px solid var(--border);
  border-left: 4px solid var(--border-strong);
  border-radius: var(--radius-md);
  background: var(--surface-sunken);
  font-size: var(--text-lg);
  font-weight: 600;
}

.report-conclusion.tone-bad {
  border-color: var(--danger);
  border-left-color: var(--danger);
  background: var(--danger-bg);
}

.report-conclusion.tone-warn {
  border-color: var(--warning);
  border-left-color: var(--warning);
  background: var(--warning-bg);
}

.report-conclusion.tone-ok {
  border-color: var(--success);
  border-left-color: var(--success);
  background: var(--success-bg);
}

/* 任务编号等元信息：标签在上、值在下，窄屏自动折列 */
.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: var(--space-3);
  margin: 0;
}

.meta-grid dt {
  color: var(--text-muted);
  font-size: var(--text-xs);
}

.meta-grid dd {
  margin: 2px 0 0;
  font-size: var(--text-13);
  word-break: break-all;
}

.meta-grid dd.mono { font-family: var(--font-mono); }

/* 统计行：数字是这张纸上最需要"一眼分清"的信息 */
.stat-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(112px, 1fr));
  gap: var(--space-3);
  margin-top: var(--space-4);
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
}

.stat-num {
  font-size: var(--text-2xl);
  font-weight: 600;
  line-height: var(--leading-tight);
  font-variant-numeric: tabular-nums;
}

.stat-label {
  color: var(--text-muted);
  font-size: var(--text-xs);
}

/* 零值的问题计数收敛：虚线 + 灰字，不抢"没问题"的语义 */
.stat.zero {
  background: transparent;
  border-style: dashed;
}

.stat.zero .stat-num { color: var(--text-disabled); }

.stat.alert {
  background: var(--danger-bg);
  border-color: var(--danger);
}

.stat.alert .stat-num { color: var(--danger); }

.stat.warn {
  background: var(--warning-bg);
  border-color: var(--warning);
}

.stat.warn .stat-num { color: var(--warning); }

/* ---------- 提示条 ---------- */

.notice {
  padding: var(--space-3) var(--space-4);
  border: 1px solid;
  border-left-width: 4px;
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
}

.notice + .notice { margin-top: var(--space-3); }

.notice-title { font-weight: 600; }
.notice-detail { margin: 2px 0 0; color: var(--text-muted); }

.notice.tone-info { border-color: var(--info); background: var(--info-bg); }
.notice.tone-warn { border-color: var(--warning); background: var(--warning-bg); }
.notice.tone-bad { border-color: var(--danger); background: var(--danger-bg); }
.notice.tone-ok { border-color: var(--success); background: var(--success-bg); }

/* ---------- 状态标签 ---------- */

.badge {
  display: inline-block;
  padding: 1px 8px;
  border: 1px solid;
  border-radius: var(--radius-pill);
  font-size: var(--text-xs);
  font-weight: 600;
  white-space: nowrap;
}

.badge.tone-ok { background: var(--success-bg); border-color: var(--success); color: var(--success); }
.badge.tone-warn { background: var(--warning-bg); border-color: var(--warning); color: var(--warning); }
.badge.tone-bad { background: var(--danger-bg); border-color: var(--danger); color: var(--danger); }
.badge.tone-running { background: var(--info-bg); border-color: var(--info); color: var(--info); }
.badge.tone-muted { background: var(--gray-100); border-color: var(--border); color: var(--text-muted); }

/* ---------- 表格 ---------- */

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
  margin-top: var(--space-3);
}

.table th,
.table td {
  border-bottom: 1px solid var(--gray-200);
  padding: var(--space-3) var(--space-2);
  text-align: left;
  vertical-align: top;
}

.table th {
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-weight: 600;
  border-bottom-color: var(--border-strong);
  white-space: nowrap;
}

.table tr:last-child td { border-bottom: none; }

.table .num {
  text-align: right;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.table .col-narrow { width: 1%; white-space: nowrap; }

/* ---------- 文件清单 ---------- */

.doc-name { font-weight: 600; word-break: break-all; }

.doc-meta {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: var(--text-xs);
}

.doc-error { color: var(--danger); font-size: var(--text-xs); }

.id-list { margin: var(--space-2) 0 0; padding: 0; list-style: none; font-size: var(--text-13); }

.id-list li { display: flex; gap: var(--space-2); }

.id-list .id-label { color: var(--text-muted); flex: none; }

.id-list .id-value { font-family: var(--font-mono); word-break: break-all; }

/* ---------- 条目列表（问题 / 风险 / 错误 / 修正） ---------- */

.item-list {
  margin: var(--space-3) 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

/* 左侧 4px 色条按严重度：问题红 / 注意橙 / 提示灰，与徽章同一口径 */
.issue-item {
  padding: var(--space-4) var(--space-5);
  border: 1px solid var(--border);
  border-left: 4px solid var(--danger);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
}

.issue-item.sev-warn { border-left-color: var(--warning); }
.issue-item.sev-muted { border-left-color: var(--gray-400); }
.issue-item.sev-ok { border-left-color: var(--success); }

.item-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.item-label {
  font-size: var(--text-base);
  font-weight: 600;
}

/* 商品归属 pill：弱化，字段名才是主角 */
.item-scope {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  color: var(--text-muted);
  font-size: var(--text-xs);
}

/* 各文件取值收进一块下沉区域，与头部/脚注分出层次 */
.value-block {
  margin-top: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  font-size: var(--text-sm);
}

.value-row {
  display: flex;
  gap: var(--space-2);
  align-items: baseline;
  flex-wrap: wrap;
}

.value-file {
  color: var(--text-muted);
  font-size: var(--text-13);
  flex: none;
}

.value-main {
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--text-body);
  word-break: break-all;
}

.value-unit { color: var(--text-muted); font-size: var(--text-xs); }

/* 原文证据：等宽 13px。原文承担证据职责，阅读级别不低于正文辅助信息 */
.value-raw {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--text-13);
  word-break: break-all;
}

.value-raw::before { content: '原文 '; font-family: var(--font-sans); }

.item-note {
  margin: var(--space-2) 0 0;
  color: var(--text-muted);
  font-size: var(--text-13);
}

.item-foot {
  margin-top: var(--space-2);
  color: var(--text-muted);
  font-size: var(--text-xs);
}

.risk-item {
  padding: var(--space-4) var(--space-5);
  border: 1px solid var(--border);
  border-left: 4px solid var(--warning);
  border-radius: var(--radius-md);
}

/* 未经规则校验的提示：虚线边框 + 下沉底色，与规则命中的风险视觉上分开 */
.risk-item.suggested {
  border-style: dashed;
  border-left: 4px solid var(--border-strong);
  background: var(--surface-sunken);
}

.risk-title { font-weight: 600; margin-top: var(--space-2); }
.risk-detail { margin: var(--space-1) 0 0; font-size: var(--text-13); }
.risk-foot { margin-top: var(--space-2); color: var(--text-muted); font-size: var(--text-xs); overflow-wrap: anywhere; }

.err-item {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
}

.err-code {
  flex: none;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.err-msg { word-break: break-word; }

/* 修正审计：before → after 一行一组 */
.corr-item {
  padding: var(--space-4) var(--space-5);
  border: 1px solid var(--border);
  border-left: 4px solid var(--info);
  border-radius: var(--radius-md);
}

.corr-head { font-size: var(--text-sm); }

.corr-reason {
  margin: var(--space-2) 0 0;
  font-size: var(--text-13);
  background: var(--surface-sunken);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
}

.change-row {
  display: flex;
  gap: var(--space-2);
  align-items: baseline;
  flex-wrap: wrap;
  margin-top: var(--space-2);
  font-size: var(--text-13);
}

.change-arrow { color: var(--text-muted); }

/* ---------- 紧凑列表（一致字段、来源、局限） ---------- */

.plain-list {
  margin: var(--space-3) 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  font-size: var(--text-sm);
}

.plain-list li {
  display: flex;
  gap: var(--space-2);
  align-items: baseline;
  flex-wrap: wrap;
}

.plain-list .plain-key { flex: none; min-width: 8em; color: var(--text-muted); }

.plain-list .plain-value { word-break: break-word; }

/* 来源条目：机构名可点（保留可追溯性），后面跟状态说明 */
.plain-list .plain-value a {
  color: var(--color-primary, oklch(52% 0.14 240));
  text-decoration: underline;
  text-underline-offset: 2px;
}

/* ---------- 杂项 ---------- */

.muted { color: var(--text-muted); }

/* 等宽文本里最长的是 64 位结果指纹，不换行会在窄屏把整页撑出横向滚动。
   overflow-wrap 而不是 word-break: break-all：只在必要时才断开长串，
   像 INV-2026-1013 这种短标识仍然整体换行。 */
.mono { font-family: var(--font-mono); overflow-wrap: anywhere; }

.foot-note {
  margin: var(--space-3) 0 0;
  color: var(--text-muted);
  font-size: var(--text-xs);
  overflow-wrap: anywhere;
}

.report-foot {
  margin-top: var(--space-2);
  color: var(--text-muted);
  font-size: var(--text-xs);
  text-align: center;
  line-height: var(--leading-relaxed);
}

/* ---------- 窄屏 ---------- */

@media (max-width: 640px) {
  body { padding: var(--space-4) var(--space-3) var(--space-8); }
  .card, .report-head { padding: var(--space-4); }
  .report-head { padding-top: calc(var(--space-5) + 4px); }
  .report-title { font-size: var(--text-xl); }
  .report-conclusion { font-size: var(--text-base); }
  .issue-item, .risk-item, .corr-item { padding: var(--space-3) var(--space-4); }
  .stat-row { grid-template-columns: repeat(auto-fit, minmax(88px, 1fr)); }
}

/* ---------- 打印 ---------- */

@media print {
  /* 纸面就是白底，桌面的点阵与投影都不该出现在 PDF 里 */
  body { background: #fff; padding: 0; }
  body::before { display: none; }

  .report { max-width: none; gap: var(--space-3); }

  .card,
  .report-head {
    box-shadow: none;
    border: 1px solid var(--border);
    padding: var(--space-4) var(--space-5);
    break-inside: auto;
  }

  /* 条目被分页切成两半最难读：整条推到下一页 */
  .issue-item,
  .risk-item,
  .err-item,
  .corr-item,
  .notice,
  .stat,
  .report-head { break-inside: avoid; }

  /* 标题不留在页尾孤行 */
  .card-title { break-after: avoid; }
  .table tr { break-inside: avoid; }
  .table thead { display: table-header-group; }

  .report-foot { margin-top: var(--space-4); }
}
`
