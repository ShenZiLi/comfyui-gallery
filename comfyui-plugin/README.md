# ComfyUI-ArtMirror 画镜图库

在 ComfyUI 侧边栏内嵌「图库」tab：浏览/管理 ComfyUI 输出图片，解析内嵌 workflow meta，AI 反推/中英翻译/评分（功能与独立版画镜一致）。

## 安装

- **ComfyUI-Manager / Desktop**：搜索 `ArtMirror 图库` 一键安装（发布到 Registry 后）
- **手动**：`git clone` 到 `custom_nodes/`，重启 ComfyUI

## 使用

安装后侧边栏出现「图库」tab；首次打开自动启动后端并扫描 ComfyUI 输出目录。设置页（tab 内）可改扫描目录、配置大模型（LLM）启用 AI 功能。

## 数据

数据库/缩略图/日志位于 ComfyUI `user/artmirror/`；默认扫描根为 ComfyUI 输出目录。

## 开发

- 同步后端：`python comfyui-plugin/sync_backend.py`（backend/app → artmirror_app/）
- 同步前端：`python comfyui-plugin/sync_frontend.py`（frontend/ → static/）
- 测试：`..\backend\.venv\Scripts\python.exe -m pip install aiohttp` 后
  `..\backend\.venv\Scripts\python.exe -m pytest comfyui-plugin -q`

## 手工冒烟（Windows）

1. 把 `comfyui-plugin` 目录拷入 ComfyUI `custom_nodes/`（或 `git clone` 到独立仓库）
2. 重启 ComfyUI（Desktop 或网页版），侧边栏出现「图库」tab
3. 点开 tab → 自动启动后端并扫描输出目录；确认图库可浏览、meta 解析、设置可保存
4. 若 503/白屏：查看 ComfyUI 控制台日志与 `user/artmirror/` 目录

## 发布 Registry（可选）

1. 用 `git subtree split` 把 `comfyui-plugin/` 拆为独立仓库 `ComfyUI-ArtMirror`
2. 填 `pyproject.toml` 的 `[tool.comfy] PublisherId`
3. `comfy node publish --install-deps`（或配置 GitHub Actions）
4. 发布 stable 后，Desktop「Manage Extensions」搜索安装验证
