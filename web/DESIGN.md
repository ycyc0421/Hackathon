# 前端设计系统

## 设计原则

1. **信息优先** - 界面服务于数据，减少装饰
2. **状态可区分** - 通过颜色+图标+文字组合传达状态
3. **操作可确认** - 动画作为反馈，确认交互生效
4. **密度自适应** - 紧凑视图用于专业用户，舒适视图降低疲劳

## 色彩系统

### 中性灰阶（冷灰，微带蓝调）
```css
--gray-50: oklch(98% 0.002 250);   /* 背景 */
--gray-100: oklch(96% 0.004 250);  /* 悬停背景 */
--gray-200: oklch(90% 0.006 250);  /* 边框 */
--gray-300: oklch(82% 0.008 250);
--gray-400: oklch(70% 0.01 250);   /* 禁用文本 */
--gray-500: oklch(58% 0.012 250);
--gray-600: oklch(45% 0.012 250);  /* 次要文本 */
--gray-700: oklch(35% 0.01 250);
--gray-800: oklch(25% 0.008 250);
--gray-900: oklch(18% 0.006 250);  /* 正文 */
```

### 主色调（沉稳蓝，专业感）
```css
--blue-50: oklch(96% 0.02 240);
--blue-100: oklch(92% 0.04 240);
--blue-500: oklch(52% 0.14 240);   /* 主操作色 */
--blue-600: oklch(45% 0.14 240);   /* hover */
--blue-700: oklch(38% 0.13 240);   /* active */
```

### 语义色
```css
--success: oklch(58% 0.13 145);    /* 绿：一致/通过 */
--warning: oklch(68% 0.15 65);     /* 琥珀：待复核/不一致 */
--danger: oklch(58% 0.16 25);      /* 红：错误/缺失 */
--info: oklch(62% 0.10 230);       /* 青：提示 */
```

**规则**：
- 所有颜色通过 CSS 变量引用
- 状态必须用颜色+图标/文字组合，不能只靠颜色
- 文本对比度达到 WCAG AA（4.5:1）

## 间距与尺寸

### 视图模式
提供紧凑和舒适两种模式，通过数据量自动切换：
- **紧凑模式**：单页数据 > 20 行时自动启用
- **舒适模式**：单页数据 ≤ 20 行或用户手动切换

```css
/* 紧凑模式 */
.compact {
  --row-height: 36px;
  --font-body: 14px;
  --space-card: var(--space-3);  /* 12px */
}

/* 舒适模式 */
.comfortable {
  --row-height: 48px;
  --font-body: 16px;
  --space-card: var(--space-6);  /* 24px */
}
```

### 基础间距
```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-6: 24px;
--space-8: 32px;
--space-12: 48px;
--space-16: 64px;
```

### 圆角与阴影
```css
--radius-sm: 4px;   /* 按钮、输入框 */
--radius-md: 8px;   /* 卡片 */
--radius-lg: 12px;  /* 模态框 */

--shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.04), 0 1px 4px rgba(0, 0, 0, 0.06);
--shadow-md: 0 2px 8px rgba(0, 0, 0, 0.08), 0 4px 16px rgba(0, 0, 0, 0.06);
```

## 字体排版

```css
--font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", 
             "Noto Sans SC", "Microsoft YaHei", sans-serif;
--font-mono: "JetBrains Mono", "SF Mono", Consolas, 
             "Liberation Mono", monospace;

--text-xs: 12px;
--text-sm: 14px;
--text-base: 16px;
--text-lg: 18px;
--text-xl: 20px;
--text-2xl: 24px;

--leading-tight: 1.25;   /* 表格 */
--leading-normal: 1.5;   /* 正文 */
--leading-relaxed: 1.75; /* 长文本 */
```

**规则**：
- body 文本：16px / 1.5（舒适）或 14px / 1.25（紧凑）
- 数字和代码：等宽字体，数字右对齐
- 标题字重 600，正文 400

## 交互状态

所有可交互元素的状态定义：

```css
/* 按钮 */
.btn {
  transition: background 120ms cubic-bezier(0.4, 0, 0.2, 1),
              transform 120ms cubic-bezier(0.4, 0, 0.2, 1);
}
.btn:hover { background: var(--blue-600); }
.btn:active { 
  background: var(--blue-700);
  transform: scale(0.98);
}
.btn:focus-visible {
  outline: 2px solid var(--blue-500);
  outline-offset: 2px;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

**规则**：
- hover：背景变深或加边框
- active：背景再深 + 轻微缩放（scale 0.98）
- focus-visible：蓝色外圈 2px
- disabled：透明度 0.5 + cursor not-allowed

## 动画系统

### 动画时长
```css
--duration-instant: 80ms;   /* 按钮反馈 */
--duration-fast: 120ms;     /* 状态切换 */
--duration-base: 200ms;     /* 页面进入 */
--duration-slow: 300ms;     /* 复杂过渡 */

--ease: cubic-bezier(0.4, 0, 0.2, 1);
```

### 使用场景

**必须做的**：
1. **按钮反馈** - hover/active 的视觉响应（80-120ms）
2. **状态切换** - 处理中→完成的淡入（120ms）
3. **上传进度** - 进度条填充动画
4. **表格 hover** - 行高亮（120ms）
5. **文件拖放** - 拖放区域高亮

**可选的**：
6. 展开/收起详情（200ms）
7. 模态框进入（200ms）
8. toast 通知滑入（200ms）

**不做的**：
- 页面切换动画（tab 直接切换）
- 数字滚动效果
- 装饰性动画
- 自动轮播

**尊重用户偏好**：
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

## 组件规范

### 按钮
```css
.btn-primary {
  background: var(--blue-500);
  color: white;
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-sm);
  min-height: 36px;
  font-weight: 500;
}

.btn-secondary {
  background: transparent;
  border: 1px solid var(--gray-200);
  color: var(--gray-900);
}
```

### 表格
- **斑马纹**：奇数行 `background: var(--gray-50)`
- **hover**：`background: var(--gray-100)`，120ms 过渡
- **表头**：字重 600，sticky 定位，`background: white`
- **对齐**：数字右对齐（等宽字体），文本左对齐
- **边框**：横向边框 `var(--gray-200)`，无竖向边框

### 表单
```css
.input {
  height: 40px;
  padding: 0 var(--space-4);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-sm);
  transition: border-color 120ms, box-shadow 120ms;
}
.input:focus {
  border-color: var(--blue-500);
  outline: none;
  box-shadow: 0 0 0 3px oklch(from var(--blue-500) l c h / 0.1);
}
.input.error {
  border-color: var(--danger);
}
```

- label 在输入框上方，14px，字重 500
- 错误状态：红色边框 + 下方错误文案
- 必填标记：红色 `*`

### StatusBadge
状态徽章统一样式：

| 状态 | 背景色 | 文字色 | 图标 |
|---|---|---|---|
| CONSISTENT | success + 0.1 alpha | success | ✓ |
| CONFLICT | warning + 0.1 alpha | warning | ⚠ |
| NOT_CHECKED | gray-100 | gray-600 | - |
| MISSING | danger + 0.1 alpha | danger | ✕ |

### 加载与空状态
- **加载**：骨架屏匹配实际布局，渐现动画 200ms
- **空状态**：必须有说明文字（"尚未评测""没有风险提示"）
- **错误**：说明什么失败 + 重试按钮

## 视图切换逻辑

### 自动切换规则
```javascript
function getViewMode(itemCount) {
  // 数据量 > 20 行自动启用紧凑模式
  if (itemCount > 20) return 'compact';
  
  // 用户手动设置优先
  const saved = localStorage.getItem('viewMode');
  if (saved) return saved;
  
  // 默认舒适模式
  return 'comfortable';
}
```

### 手动切换
在页面右上角提供切换按钮：
- 图标：`☰` (紧凑) / `☷` (舒适)
- 位置：页面标题右侧
- 状态持久化到 `localStorage`

## 深色模式（暂不实现）

预留深色模式 token 结构，但当前只实现亮色：

```css
/* 预留结构 */
[data-theme="dark"] {
  --gray-50: oklch(12% 0.006 250);
  --gray-900: oklch(96% 0.002 250);
  --blue-500: oklch(62% 0.12 240);  /* 深色下提亮 */
  /* ... */
}
```

## 响应式（移动端暂不适配）

当前只适配桌面端（≥1024px）：
- 最小宽度：1024px
- 最佳宽度：1280-1440px
- 表格在 < 1024px 时横向滚动

移动端适配留待后续独立分支。

## 无障碍

基础要求：
- 所有交互元素支持键盘操作
- focus-visible 样式明显
- 状态不只靠颜色区分（配图标/文字）
- ARIA label 补充语义
- 表单错误与输入框关联（`aria-describedby`）

---

## 实施计划

### 1. 基础设施 (`web/design-tokens`)
**优先级：最高，不阻塞其他工作**

创建 `web/src/design-tokens.css`：
- 色彩变量（中性灰 + 蓝色 + 语义色）
- 间距、圆角、阴影
- 字体、字号、行高
- 动画时长、缓动函数

重构 `web/src/styles.css`：
- 引入 design tokens
- 替换硬编码颜色为变量
- 定义视图模式 `.compact` / `.comfortable`

### 2. 错误处理 (`web/error-handling`)
**依赖：design-tokens**

- 网络失败重试（最多 3 次，指数退避）
- 超时提示（轮询 > 90s）
- 文件上传错误分类
- 全局错误边界

### 3. 加载状态 (`web/loading-states`)
**依赖：design-tokens**

- 骨架屏组件（表格、卡片、列表）
- 上传进度百分比
- 处理阶段细粒度进度
- 轮询剩余时间

### 4. 表格优化 (`web/table-improvements`)
**依赖：design-tokens**

- 斑马纹 + hover 高亮
- sticky 表头
- 数字右对齐 + 等宽字体
- 长文本省略 + tooltip

### 5. 表单优化 (`web/form-improvements`)
**依赖：design-tokens**

- 统一 input/select 样式
- 错误状态反馈
- focus 状态优化
- 文件拖放视觉反馈

### 6. 空状态与占位 (`web/empty-states`)
**依赖：design-tokens**

- "尚未评测"说明
- "没有风险"正向反馈
- 上传初始状态引导

### 7. 视图切换 (`web/view-mode-toggle`)
**依赖：design-tokens**

- 实现切换逻辑
- 添加切换按钮
- localStorage 持久化

### 8. 移动端适配 (`web/mobile-responsive`)
**依赖：所有上述分支**

- 断点系统（768px / 1024px）
- 表格卡片式展示
- 触摸友好的上传
- 底部导航

### 9. 深色模式 (`web/dark-mode`)
**依赖：design-tokens**

- 深色 token 定义
- 系统偏好检测
- 手动切换
- 全组件适配

---

## 关键决策记录

| 决策 | 理由 |
|---|---|
| 选择蓝色系 | 专业、可信，符合合规审查场景 |
| OKLCH 色彩空间 | 保证色阶亮度均匀，深浅模式更好适配 |
| 紧凑/舒适双视图 | 平衡专业用户的信息密度需求与偶尔使用者的易读性 |
| 动画只用于反馈 | 不干扰专注型工作，只确认操作生效 |
| 灰色为主，语义色克制 | 信息优先，色彩直接映射业务状态 |
| 暂不适配移动端 | 优先保证桌面端体验，移动端需求待确认 |

---

---

## 组件库选型

当前不引入完整 UI 库，保持轻量（111KB bundle）。按需引入的考虑：

### 可选依赖

**@vueuse/core**（13KB，实用工具）：
- `useLocalStorage` - 视图模式持久化
- `useDropZone` - 文件拖放上传
- `useDebounce` - 搜索防抖
- Tree-shakable，只打包用到的

**图表库**（评测页可视化）：
- Chart.js + vue-chartjs（45KB）- 推荐，轻量经典
- ECharts + vue-echarts（300KB+）- 功能强但体积大

**无头组件**（@headlessui/vue，15KB）：
- Combobox、Dialog、Listbox、Menu
- 只管逻辑和无障碍，样式完全自定义
- 与设计系统完美配合

### 不引入的原因

**完整 UI 库**（Element Plus / Ant Design Vue）：
- 体积大（100KB+），当前只用基础组件
- 样式定制成本高
- 手写更轻量，更能体现设计功底

### 引入时机

- **现在**：保持原生，等真实需求再评估
- **评测页要图表时**：加 Chart.js
- **需要复杂交互时**：加 @headlessui/vue
- **列表性能问题时**：加 vue-virtual-scroller

---

**最后更新**：2026-10-10
