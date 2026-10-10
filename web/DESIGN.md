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

**只做**：按钮反馈、状态切换淡入、上传进度、表格 hover、文件拖放高亮。
**不做**：页面切换动画、数字滚动、装饰性动画。

尊重 `prefers-reduced-motion`。

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

## 约束

- 桌面端 ≥1024px，移动端暂不适配
- 所有交互元素支持键盘操作，focus-visible 样式明显
- 文本对比度 WCAG AA（4.5:1）
- 无 UI 组件库，手写保持轻量（gzip ~39KB）
