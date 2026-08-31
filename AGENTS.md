# AGENTS.md — 画镜 ArtMirror

ComfyUI 图片/提示词资产管理工具：浏览、管理、检索本地 ComfyUI 产出图片，解析内嵌工作流 meta，并提供 AI 增强（反推提示词、中英翻译、AI 评分）。

## 项目结构

```
ArtMirror/                       # 单一真源：一次开发，双端（web / ComfyUI 插件）复用
├── src/artmirror/               # 核心包（与运行形态无关）
│   ├── main.py                  # 应用工厂 create_app()：双启动器统一入口
│   ├── models.py                # SQLModel 全部表模型
│   ├── database.py              # SQLite engine（懒创建 + reset_engine 重建绑定）
│   ├── config.py                # 环境配置（data_dir / llm_* / frontend_dir，可运行时覆盖）
│   ├── parsers/comfyui_parser.py   # PNG meta 解析（workflow/prompt 图）
│   ├── services/                # scanner / watcher / llm / meta_service
│   └── routers/                 # images/folders/tags/aggregate/settings/fs/sync
├── launchers/web/main.py        # web 端启动器（uvicorn 入口：data/ + :8000）
├── comfyui-plugin/              # 插件端启动器（embed/proxy/comfy_paths/server/web-tab）
├── frontend/                    # 无构建静态前端（唯一一份）
├── scripts/build_plugin.py      # 从真源生成自包含插件产物（发布用）
├── tests/                       # 核心包 pytest
├── pyproject.toml               # uv 管理依赖（src layout，editable 安装）
└── README.md
```

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
3. 后端逻辑改动跑单测：`uv run pytest -q`
4. **改过 `src/artmirror/` 或 `frontend/` 后，必须同步插件产物并提交**（插件端为主，解压即用依赖它）：
   ```bash
   uv run python scripts/build_plugin.py   # 同步 comfyui-plugin/{artmirror,static}
   ```
5. 前端改动**不使用自动化浏览器验证**（修改完毕后不要使用浏览器验证）；如需要由用户自行在浏览器强刷（`Cmd+Shift+R`）核对。
6. 修改提交到 **dev** 分支（当前工作分支）。

## 插件独立仓库（comfyui-gallery）

插件代码随主仓库 `comfyui-plugin/` 维护（**自包含**：启动器 + 产物 `artmirror/` + 前端 `static/`，
产物由 `scripts/build_plugin.py` 从真源同步，勿手改）。
发布时镜像推送到独立插件仓库 `https://github.com/ShenZiLi/comfyui-gallery`
（ComfyUI 侧安装用插件仓库，remote 名 `gallery`）。它是主仓库的**镜像产物**，不保留独立提交。

**每次推送主仓库 GitHub 后，必须同步更新插件仓库：**

1. 确保插件产物已同步（改过真源时）：`uv run python scripts/build_plugin.py`
2. 在插件仓库工作目录用最新 `comfyui-plugin/` 内容整体替换，提交并 force 推送（镜像覆盖）：
   ```bash
   git push -f gallery <插件分支>:main
   ```

> 新克隆插件仓库后，产物（artmirror/、static/）已随仓库携带，可直接部署到 ComfyUI `custom_nodes/`，无需再同步。

## 数据与目录

- `data/` 为运行数据（DB + 缩略图），已被 `.gitignore` 忽略；清空数据 = 删 `data/artmirror.db` 与 `data/thumbs/`。
- 扫描目录通过设置页「图片目录」注册（校验 `Path.is_dir()`，审核路径防穿越）。
- 服务本地为单用户，无鉴权；跨机访问时由前端通过局域网地址调用。

## 部署 / 自启动

个人单机工具，直接 `uv run uvicorn` 即可；无需容器/进程管理。若需后台常驻，可封装 `run.sh` 或交给本 AGENTS 规则中的重启命令。