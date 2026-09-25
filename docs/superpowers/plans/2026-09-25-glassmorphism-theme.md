# Glassmorphism 暗色主题实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在设置页添加极光靛蓝 Glassmorphism 暗色主题，保留现有主题外观与主题持久化行为。

**Architecture:** 使用现有 `data-theme` 主题键和设置保存路径。主题颜色、玻璃材质、组件适配集中在 `frontend/themes/glass.css`，由 `frontend/themes.css` 引入；设置页只增加主题元数据；功能清单记录新增主题。

**Tech Stack:** 原生 CSS、Alpine.js 设置状态、现有 FastAPI settings API；无需构建或新依赖。

---

## 文件职责

- 新建 `frontend/themes/glass.css`：定义 `glass` token、氛围背景、共享界面层的磨砂表面、控件状态及无模糊支持时的回退。每条规则以 `html[data-theme="glass"]` 开头。
- 修改 `frontend/themes.css`：追加 import，保留已有主题 import。
- 修改 `frontend/settings.html`：`Settings.themes` 追加 `glass` 主题描述和 `.tsw-glass` 色块；`pickTheme()` 不变。
- 修改 `artmirror/routers/settings.py`：在已支持主题元组中追加 `glass`，让现有 settings API 接受并持久化新主题。
- 修改 `docs/功能清单.md`：更新主题数量、增加玻璃主题功能点和更新记录。

## Task 1：注册设置页主题

**Files:**
- Modify: `frontend/settings.html`

- [x] **Step 1：在主题列表追加 glass 项**

在 `micro` 项后添加：

```js
{ key: "glass", label: "磨砂玻璃", desc: "极光靛蓝暗色 · 半透明磨砂面板与柔和蓝紫光晕",
  swatch: '<span class="tsw tsw-glass">G</span>' },
```

现有 `pickTheme(key)` 已把主题写入 localStorage 并调用 `Api.updateSettings({ theme: key })`，无需修改保存逻辑。

- [x] **Step 2：提交主题选择入口**

```powershell
git add -- frontend/settings.html
git commit -m "feat: add glass theme option"
```

## Task 2：实现隔离的玻璃暗色视觉层

**Files:**
- Create: `frontend/themes/glass.css`
- Modify: `frontend/themes.css`
- Modify: `frontend/style.css`（仅追加预览 swatch 规则）

- [x] **Step 1：追加主题 import 和 swatch**

`frontend/themes.css` 末尾添加 `@import "themes/glass.css";`；`frontend/style.css` 在现有 swatch 规则后追加：

```css
.tsw-glass { color: #f4f5ff; background: linear-gradient(135deg, #11182d 0 42%, rgba(137, 158, 255, .56) 42% 68%, #1b1730 68%); }
```

- [x] **Step 2：写入独立主题变量与组件规则**

`frontend/themes/glass.css` 定义深靛蓝 `--bg`、半透明深色 `--panel`、浅白透明描边、亮灰白主文字、淡紫蓝 `--brand`、柔和蓝紫 `--brand-glow` 和透明导航底色。页面只加固定氛围渐变；导航容器、普通 `.card`、`.dropdown-menu`、`.modal` 与输入控件使用半透明背景、`backdrop-filter: blur(15px)`、`-webkit-backdrop-filter` 和 1px 浅色细边；输入聚焦和可见键盘焦点使用品牌色光环。按钮、分段控件、菜单项、进度条、代码块、滚动条按同套色板适配。

CSS 必须限定在 `html[data-theme="glass"]`。图片本体选择器（`img`、`.thumb-wrap`、`.detail-image`）不增加滤镜、伪元素或绝对定位装饰。普通设置卡片可用玻璃表面；图库卡片的图片区继续沿用原有缩略图渲染规则。

在 `@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px)))` 下，为玻璃表面提供更实的不透明深底。添加 `prefers-reduced-motion` 规则，取消本主题控件过渡。

- [x] **Step 3：提交主题样式**

```powershell
git add -- frontend/themes.css frontend/themes/glass.css frontend/style.css
git commit -m "style: add aurora glass theme"
```

## Task 3：更新功能清单并交付验证

**Files:**
- Modify: `artmirror/routers/settings.py`
- Modify: `docs/功能清单.md`

- [x] **Step 1：允许后端保存 glass 主题值**

在 `artmirror/routers/settings.py` 的 `THEMES` 元组末尾追加 `"glass"`：

```python
THEMES = ("light", "dark", "claude", "spacex", "micro", "glass")
```

保持 `_normalize_theme()` 和 settings API 现有逻辑不变。

- [x] **Step 2：更新主题清单和记录**

将主题总数更新为六种，新增一条勾选的磨砂玻璃主题说明，指出独立 CSS 作用域及玻璃材质；在更新记录最前加入日期 `2026-09-25` 的 Glassmorphism 条目。

- [x] **Step 3：重启本地服务并确认健康状态**

在 PowerShell 终止当前监听 8000 端口的服务，等待 1 秒，再运行：

```powershell
uv run uvicorn launchers.web.main:app --host 127.0.0.1 --port 8000
```

用另一个 PowerShell 命令执行 `Invoke-RestMethod http://127.0.0.1:8000/api/health`，确认返回健康信息。按项目 `AGENTS.md`，不使用自动化浏览器验证前端；提示用户强刷后检查设置页主题卡片与玻璃外观。

- [x] **Step 4：提交后端白名单和功能清单**

```powershell
git add -- artmirror/routers/settings.py
git commit -m "feat: persist glass theme preference"
```

## 完成条件

四个主题功能提交均只包含列出的文件；加入后端白名单后再次重启服务并确认 `/api/health` 返回成功；最终 `git status --short` 中不存在本任务产生的未提交文件。当前开发工作流要求不运行用户未要求的测试。
