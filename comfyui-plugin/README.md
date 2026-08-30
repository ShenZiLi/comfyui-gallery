# ComfyUI-ArtMirror 画镜图库

在 ComfyUI 侧边栏内嵌「图库」tab：浏览/管理 ComfyUI 输出图片，解析内嵌 workflow meta，AI 反推/中英翻译/评分（功能与独立版画镜一致）。

## 安装

- **ComfyUI-Manager / Desktop**：搜索 `ArtMirror 图库` 一键安装（发布到 Registry 后）
- **手动**：`git clone` 到 `custom_nodes/`，重启 ComfyUI

## 使用

安装后侧边栏出现「图库」tab；首次打开自动启动后端并扫描 ComfyUI 输出目录。设置页（tab 内）可改扫描目录、配置大模型（LLM）启用 AI 功能。

## 数据

数据库/缩略图/日志位于 ComfyUI `user/artmirror/`；默认扫描根为 ComfyUI 输出目录。
