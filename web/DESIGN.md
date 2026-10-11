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

单证原文（`.cell-raw` / `.compare-raw`）用 13px 等宽：原文承担证据职责，
用户据它判断抽取是否可信，阅读级别不低于正文辅助信息，不用脚注级 12px。

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

- **连续输入不过渡，离散切换必过渡**：resize、拖拽这类连续输入驱动的
  布局变化不做任何过渡——每帧过渡会产生追鼠拖尾，比不动更坏；离散
  状态切换（筛选、视图互换、增删条目、切页）必须过渡。这就是
  「为什么窗口 resize 没有动画」的设计答案。
- **时序纪律**：所有 transition/animation 必须显式使用 `var(--ease)`，
  禁止缺省（linear / 浏览器默认 ease），也不另用 ease-in/ease-out 变体；
  尺寸类过渡（width / height / grid-template-rows）统一 `var(--duration-base)`，
  避免尺寸变化与颜色变化节奏不一致。
- **平级视图的互换**：同一信息的两种排布互为切换（如差异页的表格 ↔ 对照）时，
  新内容快速淡入 + 容器高度平滑过渡（距离自适应，见下条）；切换两端的视觉重量
  应相当，不出现「切过去反而更空」的方向感。
- 列表内容随筛选整体切换时，整块淡出淡入，不做逐条 stagger。
- **高度必须过渡，但距离自适应**：容器内增删内容导致高度变化时，一律走公共工具
  `utils/animateHeight.js`，禁止只 fade 不管高度——旧内容移除瞬间容器
  高度坍缩，周围内容会跳位。高度差超过阈值（`HEIGHT_TWEEN_MAX_DELTA`，300px）
  时补间拉扯感强，改用 `animateHeightAdaptive` 分流：差值内维持高度补间
  （时长封顶 `--duration-base`，不随距离变长）；超限不做高度动画——旧内容
  `--duration-fast` 淡出，新内容带轻微 translateY（4px）淡入，容器直接到位；
  页面因此变短导致 scrollY 悬空时，平滑滚动补偿到锚点卡片顶部对齐页头下沿。
  筛选切换与卡片内视图互换同一策略。
- **滚动恢复必须先于淡入**：切页恢复滚动位置在 Transition 的 `enter`
  钩子（或更早）完成，禁止 `after-enter` 才 `scrollTo`——后者会让新页
  先从头淡入再硬跳，肉眼可见。滚动记忆是通用的每页记忆：任何页面离开
  都记录 scrollY，返回时该页有记录即恢复（不限来源页），锚点跳转优先，
  无记录归零。
- **列表增删**：条目增删一律 `TransitionGroup` + 稳定 key（业务唯一值，
  禁止用数组下标——删中间项会让后续条目全部重键、补位动画失效）。
  进入/离开走 JS 精确高度钩子（`heightListItemHooks`，`:css="false"`）：
  条目留在文档流内，量真实高度后 height/padding/border/opacity 同步收放，
  文字被自己的栏位裁掉、栏位与文字一体，兄弟行随高度变化自然移动。
  禁止 absolute 脱流方案——实测栏位不收缩、文字与栏位脱离、下方内容
  突兀上移（上传页文件列表踩过的坑）。
- **高度测量必须放在 onEnter，不是 onBeforeEnter**：Vue 的 `onBeforeEnter`
  在元素【插入 DOM 之前】调用，游离节点没有布局，`offsetHeight` 恒为 0。
  在 beforeEnter 量高会让高度补间起点=终点=0：高度从不过渡，条目只靠
  padding 长出一半，等别的属性 transitionend 后内联样式被清掉瞬间弹到
  全高——表现为「出现→卡一下→弹到位」。正确姿势：beforeEnter 只做视觉
  归零防首帧闪现；onEnter 里先还原量自然高，再收起、强制 reflow、展开，
  量与还原同帧同步完成不上屏。单元素 v-if 的收合（`collapseHooks`）同理。
- **主线程重活避让动画**：文件预检测这类读文件+扫描的计算，在添加条目
  动画同帧跑会卡住补间（transition 走主线程）。预检测限读文件前缀
  （`pdfTextLayer.js` 的 `MAX_SCAN_BYTES`），并用 `requestIdleCallback`
  调度到动画之后；大段字节查找一律字节级比较，禁止循环拼字符串。

尊重 `prefers-reduced-motion`：JS 驱动的动画（平滑滚动、容器高度过渡）
需各自判断该偏好并降级。

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
- 数字列的**表头与数据对齐方式一致**：表头与数据用同一个 `.num` 类，
  对齐规则同源，不允许头左数右的错位
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

### 下拉选择（AppSelect）

自定义下拉：触发按钮 + 浮层 listbox，焦点始终在按钮上，
`aria-activedescendant` 指路。块级模式（`block`）外观对齐 `.input`，用于表单。

**使用注意**：勿把组件包在原生 `<label>` 内——点选 `<li>` 会触发 label 的
激活行为，浏览器对触发按钮合成一次 click，刚收起的浮层会被重新展开。
该合成 click 是 label 的默认行为（按祖先链确定，不走冒泡分发），组件内
选项与浮层的 click 已做 `.prevent.stop`（仅 `.stop` 拦不住），正常调用
不受影响；新增调用点时仍应避免 label 包裹（label 的激活行为对自定义
组件没有语义价值）。

### 文件列表（上传页）

已选文件清单用 `TransitionGroup` 渲染，`key` 取稳定业务值
（`fileKey = 文件名:大小`），禁止数组下标。条目进入/离开为
高度收起 + 淡出（`--duration-fast`），其余条目 move 平滑补位
（`--duration-base`）。

**容器纪律**（适用于一切 TransitionGroup 列表）：

- 容器常驻挂载，**不用 `v-if` 包容器**：`v-if` 在删到最后一项时会把容器
  直接移除，条目离场钩子不执行，只剩窗口硬 resize。空态改用类绑定
  （`.file-list--empty`）把容器自身的边框/margin 一并过渡，首尾项的
  增删与中间项同样连贯。
- **持久状态列表禁用 `appear`**：`appear` 的语义是"每次挂载都播进入动画"。
  文件列表这类状态提升在 App 层、切页后还在的列表，加 `appear` 会导致
  每次切回页面都重播。条目插入本身就会触发进入钩子，不需要 `appear`。

### 状态徽章

| 状态 | 背景 | 文字 | 图标 |
|---|---|---|---|
| CONSISTENT | success + 0.1α | success | ✓ |
| CONFLICT | warning + 0.1α | warning | ⚠ |
| NOT_CHECKED | gray-100 | gray-600 | - |
| MISSING | danger + 0.1α | danger | ✕ |

### 加载与空状态

- **加载**：骨架屏匹配实际布局，渐现 200ms
- **空状态**：纯文字排版（标题 + 说明），**不用 emoji 插图**——企业工具，保持克制；
  必须有说明文字（"尚未评测""没有风险提示"）
- **通过态收敛**：全通过的正向确认（"没有需要处理的条目""没有风险提示"）
  用一条细窄绿色 NoticeBar 一句话带过，**不用居中大空状态**
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

- 触发：卡片头部**最左**的分段控件「表格 | 对照」（`.view-switch`），默认「表格」；
  视线顺序为 切换方式 → 字段 → 徽章。
  `role="group"` + `aria-label="查看方式"`，各按钮用 `aria-pressed` 表达当前选中，
  不使用 `aria-expanded`/chevron 展开语义
- 切换动画：离场内容立即隐藏（**不做离场动画、不用 absolute 定位**——crossfade
  曾使父容器高度中途坍缩、整列抖动），新内容快速淡入（`--duration-fast`）；
  容器高度只由 JS 从旧高度平滑过渡到新高度（`--duration-base`）。
  测量目标高度时须先还原最终态再量（`overflow:hidden` 使容器成为 BFC，
  子元素 margin 不再折叠，直接量会虚高一个 margin）。
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

- 承载：3px 左边带 + 底色的小卡，字号 `--text-base`、字重 500
- **颜色跟随语气（tone）**，tone 与文案同源推导（`utils/reportConclusion.js`），
  不出现"坏消息配蓝底"的错位：有问题条目 `--danger` 红；含未校验或 PARTIAL
  `--warning` 橙；COMPLETED 且比对条目全部一致 `--success` 绿；其余中性灰
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

## 状态层级

页面随切页重挂载，**页面级 ref 切页即丢**。需要在页面间存活的状态一律提升到
App 层（provide/inject）：检查任务（task）、上传页表单（文件列表/目的国/备注/
扫描件警告）、评测数据缓存。任务还在、输入却丢了，就是层级放错的信号。

### 「需关注」口径

一条比对是否需要人工复核，由 `utils/needsReview.js` 的 `needsReview` 统一判定：
比对状态 ∈ {CONFLICT, MISSING_IN_SOME, NOT_CHECKED, UNRECOGNIZED}，或任一取值的
`field_status === 'LOW_CONFIDENCE'`（徽章「请核对」）。MATCH 比对也可能含低可信
取值——只看状态集合会把它们漏到「全部」筛选里。差异页筛选与计数、报告页问题
条目、顶栏差异页角标三处共用这一函数，**不允许各页面再写等价判断**。

## 约束

- 桌面端 ≥1024px，移动端暂不适配
- 所有交互元素支持键盘操作，focus-visible 样式明显
- 文本对比度 WCAG AA（4.5:1）
- 无 UI 组件库，手写保持轻量（gzip ~39KB）
