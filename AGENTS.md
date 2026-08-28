# AGENTS.md — 画镜 ArtMirror

ComfyUI 图片/提示词资产管理工具：浏览、管理、检索本地 ComfyUI 产出图片，解析内嵌工作流 meta，并提供 AI 增强（反推提示词、中英翻译、AI 评分）。

## 项目结构

```
ArtMirror/
├── backend/                 # Python + FastAPI 后端（单进程 = API + 前端静态托管）
│   ├── app/
│   │   ├── main.py          # 应用入口：启动 watcher、托管静态、NoCache 静态
│   │   ├── models.py        # SQLModel 全部表模型
│   │   ├── database.py      # SQLite engine（check_same_thread=False, timeout=30）
│   │   ├── config.py        # 环境配置（data_dir / llm_* / frontend_dir）
│   │   ├── parsers/comfyui_parser.py   # PNG meta 解析（workflow/prompt 图）
│   │   ├── services/
│   │   │   ├── scanner.py   # 递归扫描、sha 去重、缩略图、建绝对路径 Folder
│   │   │   ├── meta_service.py  # 解析结果落库 + 标签
│   │   │   └── watcher.py   # 后台增量扫描 + 同步版本号
│   │   └── routers/         # images/folders/tags/aggregate/settings/fs/sync
│   ├── tests/               # pytest
│   ├── pyproject.toml       # uv 管理依赖
│   └── uv.lock
├── frontend/                # 无构建静态前端（HTML+CSS+JS+Alpine.js）
│   ├── gallery.html / settings.html / image.html / index.html
│   ├── api.js               # 前端 API 层（优先后端，离线回退 mock）
│   ├── app.js               # 公共脚本：导航注入、明暗主题、高亮
│   └── style.css
└── README.md
```

## 技术栈与关键约定

- **后端**：Python 3.12 + FastAPI + uvicorn + SQLModel(SQLite) + Pillow + httpx；依赖用 `uv` 管理。
- **前端**：无构建静态页；响应式由 Alpine.js + 手写 CSS 实现；封装在 `api.js` 的 `App` / `Api` 全局对象。
- **数据库**：SQLite `data/artmirror.db`；每图**只存引用**(`abs_path`/`sha256`)与 meta，不存图片字节；缩略图在 `data/thumbs/<sha>.webp`。
- **图片目录**：入库存**对本地路径的链接**，不拷贝导入。实时同步由 `watcher.py` 后台 20s 增量扫描 + 递增版本号 + 前端 3s 轮询 `/api/sync/version` 实现。
- **Folder.path 一律绝对路径**；`is_deleted=1` 用于软删。
- 静态资源已启用 `Cache-Control: no-cache`，前端改动刷新即生效。

## 常用命令

在 `backend/` 目录下执行：

```bash
# 安装/同步依赖（首次）
uv sync

# 运行测试（11 例）
uv run pytest -q

# 启动服务（API + 前端托管）
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# 前端无需独立服务，浏览器访问：
#   http://127.0.0.1:8000/gallery.html  图库
#   http://127.0.0.1:8000/settings.html 设置
#   http://127.0.0.1:8000/docs          后端 OpenAPI
```

## 强制工作流

> **每次修改代码后，必须重启服务进行验证。**

1. 修改后端或前端文件后，**立即重启后端服务**（否则改动不生效）：
   ```bash
   lsof -ti:8000 | xargs kill -9 2>/dev/null; sleep 1
   cd backend && (uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 >/tmp/am.log 2>&1 &)
   ```
2. 确认可访问：`curl -s http://127.0.0.1:8000/api/health`
3. 后端逻辑改动跑单测：`uv run pytest -q`
4. 前端改动用浏览器强刷（`Cmd+Shift+R`）核对。
5. 修改提交到 **dev** 分支（当前工作分支）。

## 数据与目录

- `data/` 为运行数据（DB + 缩略图），已被 `.gitignore` 忽略；清空数据 = 删 `data/artmirror.db` 与 `data/thumbs/`。
- 扫描目录通过设置页「图片目录」注册（校验 `Path.is_dir()`，审核路径防穿越）。
- 服务本地为单用户，无鉴权；跨机访问时由前端通过局域网地址调用。

## 部署 / 自启动

个人单机工具，直接 `uv run uvicorn` 即可；无需容器/进程管理。若需后台常驻，可封装 `backend/run.sh` 或交给本 AGENTS 规则中的重启命令。