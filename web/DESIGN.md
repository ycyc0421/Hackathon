# 前端设计系统

## 原则

1. **信息优先** — 界面服务于数据，减少装饰
2. **状态可区分** — 颜色+图标+文字组合，不只靠颜色
3. **操作可确认** — 动画只用于反馈，确认交互生效
4. **不伪造数据** — 缺失的可信度、未运行的评测一律留空

## Token

### 色彩

```css
/* 中性灰（冷灰，微带蓝调） */
--gray-50: oklch(98% 0.002 250);   /* 背景 */
--gray-100: oklch(96% 0.004 250);  /* 悬停 */
--gray-200: oklch(90% 0.006 250);  /* 边框 */
--gray-400: oklch(70% 0.01 250);   /* 禁用文本 */
--gray-600: oklch(45% 0.012 250);  /* 次要文本 */
--gray-900: oklch(18% 0.006 250);  /* 正文 */

/* 主色（沉稳蓝） */
--blue-500: oklch(52% 0.14 240);
--blue-600: oklch(45% 0.14 240);   /* hover */
--blue-700: oklch(38% 0.13 240);   /* active */

/* 语义色 */
--success: oklch(58% 0.13 145);    /* 一致/通过 */
--warning: oklch(68% 0.15 65);     /* 待复核/不一致 */
--danger: oklch(58% 0.16 25);      /* 错误/缺失 */
--info: oklch(62% 0.10 230);       /* 提示 */
```

### 间距 / 圆角 / 阴影

```css
--space-1: 4px;  --space-2: 8px;   --space-3: 12px;
--space-4: 16px; --space-6: 24px;  --space-8: 32px;

--radius-sm: 4px;   /* 按钮、输入框 */
--radius-md: 8px;   /* 卡片 */

--shadow-sm: 0 1px 2px rgba(0,0,0,0.04), 0 1px 4px rgba(0,0,0,0.06);
--shadow-md: 0 2px 8px rgba(0,0,0,0.08), 0 4px 16px rgba(0,0,0,0.06);
```

### 字体

```css
--font-sans: -apple-system, "Segoe UI", "Noto Sans SC", "Microsoft YaHei", sans-serif;
--font-mono: "JetBrains Mono", "SF Mono", Consolas, monospace;

--text-xs: 12px;  --text-sm: 14px;  --text-base: 16px;
--text-lg: 18px;  --text-xl: 20px;
```

数字和代码用等宽字体，数字右对齐。标题字重 600，正文 400。

### 动画

```css
--duration-fast: 120ms;    /* 状态切换 */
--duration-base: 200ms;    /* 页面进入 */
--ease: cubic-bezier(0.4, 0, 0.2, 1);
```

**只做**：按钮反馈、状态切换淡入、筛选 chips 切换、表格与对照的视图切换、
页面切换（顶栏标签间 out-in 淡入淡出）、上传进度、表格 hover、文件拖放高亮。
**不做**：数字滚动、装饰性动画。

补充原则：

- **平级视图的互换**：同一信息的两种排布互为切换（如差异页的表格 ↔ 对照）时，
  用交叉淡入淡出（离场内容脱离文档流）+ 容器高度平滑过渡；切换两端的视觉重量
  应相当，不出现「切过去反而更空」的方向感。
- 列表内容随筛选整体切换时，整块淡出淡入，不做逐条 stagger。

尊重 `prefers-reduced-motion`：全局媒体查询已把所有过渡/动画时长压为瞬时；
JS 驱动的动画（平滑滚动、容器高度过渡）需各自判断该偏好并降级。

## 组件

### 按钮

```css
.btn-primary {
  background: var(--blue-500);
  color: white;
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-sm);
  min-height: 36px;
}
```

- hover：背景变深
- active：再深 + `scale(0.98)`
- focus-visible：蓝色外圈 2px
- disabled：透明度 0.5

### 表格

- 斑马纹：奇数行 `var(--gray-50)`
- hover：`var(--gray-100)`，120ms 过渡
- 表头：字重 600，sticky，`background: white`
- 数字右对齐（等宽），文本左对齐
- 横向边框 `var(--gray-200)`，无竖向边框

### 表单

```css
.input {
  height: 40px;
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-sm);
}
.input:focus {
  border-color: var(--blue-500);
  box-shadow: 0 0 0 3px oklch(from var(--blue-500) l c h / 0.1);
}
```

label 在输入框上方。错误：红色边框 + 下方错误文案。

### 状态徽章

| 状态 | 背景 | 文字 | 图标 |
|---|---|---|---|
| CONSISTENT | success + 0.1α | success | ✓ |
| CONFLICT | warning + 0.1α | warning | ⚠ |
| NOT_CHECKED | gray-100 | gray-600 | - |
| MISSING | danger + 0.1α | danger | ✕ |

### 加载与空状态

- **加载**：骨架屏匹配实际布局，渐现 200ms
- **空状态**：必须有说明文字（"尚未评测""没有风险提示"）
- **错误**：说明什么失败 + 重试按钮

### 文件 chips（报告页）

文件名清单压缩为 chips，一行多份，状态靠色点快分。

- 结构：状态色点（8px 圆，`processStatus` 的 tone → 语义色）+ 文件名 + 类型
- 失败文件：`error_message` 放 chip 第二行（`--danger` 小号字），压缩布局也不丢错误信息
- 布局：`flex-wrap` + `gap: var(--space-2)`，边框 `var(--border)`，圆角 `var(--radius-md)`

### 并排对照面板（差异页 ComparePane）

比对卡片的左右对照视图，回答「几份文件摆在一起，差异在哪」。

**为什么是视图切换而不是就地展开**：四行表格与并排对照是同一信息的**两种排布、互为平级**，
不是概要/详情的展开关系。此前用 ▶ 展开语义时，展开后的三列浅面板反而比收起态的
四行表格更矮——「展开却看到更少」违反直觉。因此触发方式改为分段控件切换。

- 触发：卡片头部右侧的分段控件「表格 | 对照」（`.view-switch`），默认「表格」；
  `role="group"` + `aria-label="查看方式"`，各按钮用 `aria-pressed` 表达当前选中，
  不使用 `aria-expanded`/chevron 展开语义
- 切换动画：交叉淡入淡出（离场内容 `position: absolute` 脱离文档流，由入场内容撑开
  高度），容器高度由 JS 从旧高度平滑过渡到新高度（`--duration-base`），
  `prefers-reduced-motion` 下全局压为瞬时
- 状态模型：每张卡片记录当前视图（`table | compare`），非 Set 展开态；不持久化，
  切页重挂载后回到表格视图
- 布局：`grid` + `repeat(auto-fit, minmax(220px, 1fr))`，多文件自动换行平铺
- 每列：文件名（muted 小字）→ 值（等宽 600）+ 页码 → 原文 → 字段状态徽章 + 「查看原文」链接
- 差异强调：仅「CONFLICT 且本列归一值与其他列不同」的那一列，左边框 3px `--danger` + `--danger-bg`；一致列保持中性
- 降级：无 File 对象（mock）不渲染「查看原文」；`page` 为 null 不显示页码；值为 null 显示「—」

### 报告页结论条与统计卡

**结论条**（`.report-conclusion`）：检查概要的开头结论是全页最重要的一句话，
先于统计数字出现，必须一眼可见。

- 承载：主色 3px 左边带 + `--blue-50` 底色 + `--blue-200` 边框的小卡，
  字号 `--text-base`、字重 500
- 容器保持中性（主色而非语义色）：结论文案有好有坏，不由容器预设语气
- summary 缺失时整段不渲染，不替后端下结论

**统计卡**（`.stat-row` / `.stat`）：每个统计数字一张小卡
（边框 + `--radius-md`），核心是「需要处理」的数字要分层：

- 零值（没有问题）：数字收敛为 `--text-muted`，无底色，不抢「没问题」的语义
- 非零：底色 + 边框 + 数字同语义色（不一致 `--danger`，部分缺失/无法比对 `--warning`）
- 中性计数（文件、抽取字段、风险提示）：保持默认卡片样式

**问题条目**（`.issue-item`）：头部（字段名 + 商品归属 pill + 徽章）→
取值区（`--gray-50` 浅底块，值用等宽 600）→ 脚注链接，三层间距
`--space-2` 节奏统一；商品归属 pill 弱化处理，查不到目录时不显示、不猜。

### 扫描件警告（上传页）

PDF 文本层预检测命中的行内标记（`.scan-warn`）。

- 位置：文件名右侧行内，warning 边框 + 底色 + 文字
- `cursor: help` + `title` 放完整说明；措辞一律「可能」（启发式会误判），不阻止提交

## 约束

- 桌面端 ≥1024px，移动端暂不适配
- 所有交互元素支持键盘操作，focus-visible 样式明显
- 文本对比度 WCAG AA（4.5:1）
- 无 UI 组件库，手写保持轻量（gzip ~39KB）
