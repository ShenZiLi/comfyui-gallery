# 亮/暗色主题切换 · 落地方案

> 画镜 ArtMirror 主题切换动效的实现说明（View Transitions + CSS `clip-path` 圆形扩散）。

## 一、目标

点击右上角的亮/暗模式按钮时，页面从按钮位置**圆形扩散到全屏**完成主题切换，使明暗切换过渡自然、不生硬，提升视觉质感；同时保留主题持久化（刷新后仍为上次选择）。

## 二、技术选型

- **View Transitions API**（`document.startViewTransition`）：浏览器原生页面级过渡能力，由浏览器在「旧快照 → 新快照」之间运行动画，无需任何库。
- **CSS `clip-path: circle()`**：借助 `::view-transition-old/new(root)` 对根节点做圆形裁剪扩散，实现“从右上角展开”的视觉。
- **CSS 变量 + `data-theme` 属性**：亮/暗两套配色由 `[data-theme="dark"]` 切换，动画只作用于过渡层，配色本身仍走 CSS 变量。
- 不支持 View Transitions 的浏览器**自动回退为直接切换**，不影响功能。

> 为何不用 JS 动画库：本项目为原生 JS + Alpine、无构建流程；View Transitions 已是现代浏览器的标准方案，零依赖、走合成器线程性能更好，适合“页面/主题级过渡”。React 系（Motion/Framer）不适用，GSAP 对本场景过重。

## 三、实现

### 3.1 涉及文件

| 文件 | 作用 |
|---|---|
| `frontend/app.js` | 主题状态读取/写入、按钮图标、触发过渡 |
| `frontend/style.css` | `[data-theme]` 变量、View Transitions 的裁剪扩散动画 |

### 3.2 触发与状态（`frontend/app.js`）

导航栏由 `navHTML()` 注入一个按钮（`#theme-toggle`）。切换逻辑：

```js
function currentTheme() {
  return localStorage.getItem("am-theme") || "light";
}

function applyTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  localStorage.setItem("am-theme", t);
  var btn = document.getElementById("theme-toggle");
  if (btn) btn.innerHTML = t === "dark" ? ICON_SUN : ICON_MOON;
}

function toggleTheme() {
  var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  // 用 View Transitions 做圆形扩散动效（从右上角按钮处展开至全屏）
  if (document.startViewTransition) {
    try {
      document.startViewTransition(function () { applyTheme(next); });
      return;
    } catch (e) {}
  }
  applyTheme(next); // 降级
}
```

要点：
- 状态存于 `localStorage["am-theme"]`，取值 `light | dark`。
- `startViewTransition(cb)` 在回调里切换 `data-theme`，浏览器自动捕获并播放过渡。
- 按钮图标在亮色显示“月”（点击切暗），暗色显示“日”（点击切亮）。

### 3.3 扩散动画（`frontend/style.css`）

```css
/* 亮/暗主题切换：从右上角按钮处圆形扩散至全屏（View Transitions） */
::view-transition-old(root) { animation: vt-out .3s ease-out; mix-blend-mode: normal; }
::view-transition-new(root) { animation: vt-in .55s cubic-bezier(.45,.05,.2,1); mix-blend-mode: normal; }

@keyframes vt-out {
  to { opacity: .55; transform: scale(.99); }
}
@keyframes vt-in {
  from { clip-path: circle(0% at 100% 0%); transform: scale(.99); }
  to   { clip-path: circle(150% at 100% 0%); transform: scale(1); }
}

@media (prefers-reduced-motion: reduce) {
  ::view-transition-new(root),
  ::view-transition-old(root) { animation: none; }
}
```

动画说明：
- **旧页（old）**：平滑缩小+淡出到 55%，避免扩散边缘生硬。
- **新页（new）**：`clip-path` 圆形半径从 `0%`（右上角 `100% 0%`，即按钮位置）扩散到 `150%`（覆盖全屏），并略微从 `0.99` 放大回 `1`；缓动 `cubic-bezier(.45,.05,.2,1)` 平滑收尾。
- 按钮位于右上角，故裁剪原点取 `100% 0%`。
- 尊重 `prefers-reduced-motion`。

### 3.4 明暗配色（已有，供参考）

亮/暗两套变量通过 `html[data-theme="dark"]` 覆盖（例）：

```css
:root { --bg: #f5f6f8; --text: #1a1d21; /* 亮色 */ }
html[data-theme="dark"] { --bg: #0f1218; --text: #e6e8ec; /* 暗色 */ }
```

## 四、浏览器兼容与降级

- **支持** `document.startViewTransition`：自动播放圆形扩散。
- **不支持 / 出错**：`try/catch` 兜底，直接调用 `applyTheme(next)`，无动画但功能正常。
- `prefers-reduced-motion: reduce`：关闭动画，避免对晕动敏感用户造成不适。

## 五、可选优化（后续）

1. **跟随点击位置扩散**：在 `toggleTheme` 里读按钮 `getBoundingClientRect()`，把圆心坐标写成 CSS 变量（如 `--tx`/`--ty`），再用于 `clip-path: circle(... at var(--tx) var(--ty))`，让扩散严格从按钮中心出发。
2. **同步明暗配色元信息**：可在 `<html>` 加 `<meta name="color-scheme" content="dark">`，让滚动条/表单控件也跟随主题。
3. **主题动画复用**：如果后续做“设置页实时预览主题”，可把 `applyTheme` + 过渡封装成复用函数。
4. **防首屏闪烁**：内联一段小脚本在 `head` 里提前读 `localStorage` 并设 `data-theme`，避免刷新时亮暗闪现。

## 六、验证方式

1. 启动服务后访问 `gallery.html`。
2. 点击右上角按钮：应看到从按钮处圆形扩散的全屏切换，旧页缩放淡出、新页扩散进入。
3. 刷新页面：主题保持不变（`localStorage` 持久化）。
4. 浏览器开发者工具切“减少动态效果”（prefers-reduced-motion）后点击：无动画、直接切换。