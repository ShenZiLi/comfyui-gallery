# AGENTS.md — 画镜 ArtMirror

ComfyUI 图片/提示词资产管理工具：浏览、管理、检索本地 ComfyUI 产出图片，解析内嵌工作流 meta，并提供 AI 增强（反推提示词、中英翻译、AI 评分）。

## 项目结构

```
ArtMirror/                       # 仓库根即 ComfyUI 插件（clone 放入 custom_nodes/ArtMirror 解压即用）
├── __init__.py                  # 插件入口：NODE_CLASS_MAPPINGS / WEB_DIRECTORY / 路由注册
├── web/artmirror-tab.js         # 侧边栏「图库」tab 扩展
├── requirements.txt             # 插件加载时自动安装依赖（comfyui/install_deps.py）
├── artmirror/                   # 核心包（真源，直接开发）
│   ├── main.py                  # 应用工厂 create_app()：双启动器统一入口
│   ├── models.py                # SQLModel 全部表模型
│   ├── database.py              # SQLite engine（懒创建 + reset_engine 重建绑定）
│   ├── config.py                # 环境配置（data_dir / llm_* / frontend_dir，可运行时覆盖）
│   ├── parsers/comfyui_parser.py   # PNG meta 解析（workflow/prompt 图）
│   ├── services/                # scanner / watcher / llm / meta_service
│   └── routers/                 # images/folders/tags/aggregate/settings/fs/sync
├── comfyui/                     # 插件集成层（ComfyUI 适配，与核心分层）
│   ├── embed.py                 # 进程内后台线程运行 FastAPI（临时端口）
│   ├── routes.py                # PromptServer 路由注册 + /artmirror/* 反代
│   ├── paths.py                 # ComfyUI 路径解析（user/output 目录）
│   └── install_deps.py          # 加载时自动检测并安装缺失依赖（解压即用）
├── launchers/web/main.py        # web 端辅助启动器（uvicorn 入口：data/ + :8000）
├── frontend/                    # 前端（唯一一份，零构建；双端共用）
├── scripts/build_plugin.py      # 打包单文件 zip（分发给小白）
├── tests/                       # pytest（tests/ 核心 + tests/plugins/ 插件集成）
├── pyproject.toml               # uv 管理依赖（editable 安装 artmirror）
└── README.md
```

> **核心约定：仓库根即插件，改 `artmirror/` 或 `frontend/` 即双端生效，无任何构建/同步步骤。**

## 技术栈与关键约定

- **后端**：Python 3.12 + FastAPI + uvicorn + SQLModel(SQLite) + Pillow + httpx；依赖用 `uv` 管理。
- **前端**：无构建静态页；响应式由 Alpine.js + 手写 CSS 实现；封装在 `api.js` 的 `App` / `Api` 全局对象。
- **数据库**：SQLite `data/artmirror.db`；每图**只存引用**(`abs_path`/`sha256`)与 meta，不存图片字节；缩略图在 `data/thumbs/<sha>.webp`。
- **图片目录**：入库存**对本地路径的链接**，不拷贝导入。实时同步由 `watcher.py` 后台 20s 增量扫描 + 递增版本号 + 前端 3s 轮询 `/api/sync/version` 实现。
- **Folder.path 一律绝对路径**；`is_deleted=1` 用于软删。
- **图片不可被遮盖**：图片上方不允许叠加图标或文字（如角标、徽章）进行遮盖；相关提示信息放在图片之外展示。
- 静态资源已启用 `Cache-Control: no-cache`，前端改动刷新即生效。

## 常用命令

在仓库根目录下执行：

```bash
# 安装/同步依赖（首次）
uv sync

# 运行测试
uv run pytest -q

# 启动服务（API + 前端托管）
uv run uvicorn launchers.web.main:app --host 0.0.0.0 --port 8000

# 前端无需独立服务，浏览器访问：
#   http://127.0.0.1:8000/gallery.html  图库
#   http://127.0.0.1:8000/settings.html 设置
#   http://127.0.0.1:8000/docs          后端 OpenAPI
```

## 文档维护

- 每次**新增功能点**，必须同步记录到 `docs/功能清单.md`（归类：优先按页面，其次按功能类型），并新增一行「更新记录」。

## 强制工作流

> **每次修改代码后，必须重启服务进行验证。**

1. 修改后端或前端文件后，**立即重启后端服务**（否则改动不生效）：
   ```bash
   lsof -ti:8000 | xargs kill -9 2>/dev/null; sleep 1
   (uv run uvicorn launchers.web.main:app --host 127.0.0.1 --port 8000 >/tmp/am.log 2>&1 &)
   ```
2. 确认可访问：`curl -s http://127.0.0.1:8000/api/health`
3. 后端逻辑改动跑单测：`uv run pytest -q`（tests/ 核心 + tests/plugins/ 插件集成）
4. **仓库根即插件**：改 `artmirror/` 或 `frontend/` 即插件端同步生效，无构建步骤；发布 zip 可选：
   `uv run python scripts/build_plugin.py`（生成 build/ArtMirror-comfyui-plugin.zip）
5. 前端改动**不使用自动化浏览器验证**（修改完毕后不要使用浏览器验证）；如需要由用户自行在浏览器强刷（`Cmd+Shift+R`）核对。
6. 修改提交到 **dev** 分支（当前工作分支）。

## 插件独立仓库（comfyui-gallery）

仓库根即插件（`__init__.py` + `web/` + `requirements.txt` + `artmirror/`），
可直接作为 ComfyUI 插件安装。另设独立插件仓库
`https://github.com/ShenZiLi/comfyui-gallery`（remote 名 `gallery`）供 ComfyUI 侧
安装，内容为主仓库的**镜像**，不保留独立提交。

**每次推送主仓库 GitHub 后，可选同步插件仓库（镜像覆盖）：**

```bash
git push -f gallery <分支>:main
```

> 小白分发：`uv run python scripts/build_plugin.py` 生成单文件 zip，解压到
> `custom_nodes/ArtMirror` 重启即用（依赖由 ComfyUI 自动安装）。

## 数据与目录

- `data/` 为运行数据（DB + 缩略图），已被 `.gitignore` 忽略；清空数据 = 删 `data/artmirror.db` 与 `data/thumbs/`。
- 扫描目录通过设置页「图片目录」注册（校验 `Path.is_dir()`，审核路径防穿越）。
- 服务本地为单用户，无鉴权；跨机访问时由前端通过局域网地址调用。

## 部署 / 自启动

个人单机工具，直接 `uv run uvicorn` 即可；无需容器/进程管理。若需后台常驻，可封装 `run.sh` 或交给本 AGENTS 规则中的重启命令。