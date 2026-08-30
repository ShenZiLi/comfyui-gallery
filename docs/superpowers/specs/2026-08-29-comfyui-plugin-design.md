# ArtMirror × ComfyUI 插件集成设计

> 日期：2026-08-29 ｜ 状态：待审阅 ｜ 目标：把画镜 ArtMirror 以「自定义节点 + 前端扩展」形式集成进 ComfyUI（含 Desktop），发布到 Comfy Registry 一键安装

## 1. 目标

将 ArtMirror（ComfyUI 图片/提示词资产管理工具：图库浏览、内嵌 workflow meta 解析、AI 反推/翻译/评分）打包为一个 ComfyUI 自定义节点包 `ComfyUI-ArtMirror`，在 ComfyUI **侧边栏嵌入「图库」tab**（iframe），后端挂载到 ComfyUI 服务器，**功能与独立版完全对齐**，发布到 Comfy Registry 供 Desktop/网页版用户一键安装。

## 2. 已确认决策（与用户逐项对齐）

| 决策点    | 选择                                              |
| ------ | ----------------------------------------------- |
| 集成体验   | **侧边栏/底部「图库」tab 内嵌 iframe**（类 SDFX 模式）          |
| 交付形态   | **发布到 Comfy Registry**（Desktop 内置 Manager 一键安装） |
| 后端运行形态 | **挂 ComfyUI 服务器**（aiohttp 反向代理桥接进程内 FastAPI）    |
| 功能范围   | **全功能对齐**（图库/解析/AI 反推·翻译·评分/设置/导入）              |
| 与独立版关系 | 独立版（uv/启动.bat）保留不变；插件为新增独立仓库                    |

## 3. 架构总览

```
ComfyUI 进程（aiohttp 服务器，端口 8188）
│
├─ 前端扩展（web/artmirror-tab.js）
│    └─ 侧边栏「图库」tab → <iframe src="/artmirror/gallery.html">
│
└─ 自定义节点路由（server.py，PromptServer.instance.routes）
     └─ GET/POST /artmirror/*  → 反向代理 →
          └─ 进程内 FastAPI/uvicorn 后台线程（127.0.0.1 临时端口）
               ├─ /api/*        ArtMirror 全部 REST 接口（routers: images/folders/tags/aggregate/settings/fs/sync）
               └─ /*            ArtMirror 静态前端（frontend 副本，NoCacheStaticFiles）
```

**核心机制**：ComfyUI 是 aiohttp，ArtMirror 是 FastAPI。不做逐条重写，而是**在 ComfyUI 进程内用后台线程跑 uvicorn（监听 127.0.0.1 临时端口 0）**，再在 PromptServer 上挂 `/artmirror/*` 的 aiohttp 反向代理路由转发到该临时端口。

**由此获得**：

* **后端零改动 → 全功能对齐免费获得**；前端 iframe 与 API 均走 ComfyUI 同源 `/artmirror/` → **无 CORS、无端口冲突**（对外只有 8188）

* 生命周期随 ComfyUI：后台线程 daemon，随进程退出；懒启动 + 单例守卫

* `WEB_DIRECTORY` 只服务 `.js` 的约束正好满足：HTML 前端由代理路由托管

## 4. 插件仓库结构（新仓库 ComfyUI-ArtMirror）

```
ComfyUI-ArtMirror/
├── __init__.py            # 注册占位节点（NODE_CLASS_MAPPINGS 非空包才被加载）+ WEB_DIRECTORY="web" + 懒启动入口
├── pyproject.toml         # [project] 依赖 + [tool.comfy] Registry 发布元数据
├── server.py              # aiohttp 反向代理路由：/artmirror/* → 进程内 FastAPI
├── artmirror_embed.py     # 进程内 uvicorn 线程（单例、临时端口、懒启动、DB 定位）
├── web/
│   └── artmirror-tab.js   # 前端扩展：registerSidebarTab 注册「图库」tab，iframe
├── static/                # ArtMirror 静态前端副本（gallery.html / api.js / style.css / vendor/...）
├── sync_frontend.py       # 开发脚本：从 ArtMirror 主仓库 frontend/ 同步到 static/
└── README.md              # 安装/使用/发布说明
```

## 5. 组件设计

### 5.1 `__init__.py` — 包入口

* 导出 `NODE_CLASS_MAPPINGS = {"ArtMirrorLauncher": ...}`、`NODE_DISPLAY_NAME_MAPPINGS`：注册一个最小占位节点（无实际图逻辑，仅让包被识别为自定义节点包；也可做成「在图中双击打开图库」的辅助节点，首版取最小占位）。

* 声明 `WEB_DIRECTORY = "web"`。

* 模块导入时**不**启动服务（避免拖慢 ComfyUI 启动与影响无头场景）；服务由首次 `/artmirror/*` 请求懒启动。

### 5.2 `artmirror_embed.py` — 进程内 FastAPI 线程

* 单例：`threading.Lock` + 模块级状态，保证仅一个实例。

* `start() -> int`：

  1. `from app import main as app_main`（import ArtMirror 的 FastAPI app——以子包方式随插件分发，见 §6）
  2. 定位运行数据：`data_dir = folder_paths.get_user_directory() / "artmirror"`（Desktop 更新/快照不会覆盖 `user/`）
  3. 默认扫描根：`folder_paths.get_output_directory()`（运行时获取，不写死）
  4. `uvicorn.Config(app, host="127.0.0.1", port=0, log_config=<落盘 dictConfig>, access_log=False)`；`port=0` 由 OS 分配临时端口
  5. `threading.Thread(target=server.run, daemon=True)` 启动；轮询读取 `server.servers[0].sockets[0].getsockname()[1]` 得到实际端口
  6. 记录端口到模块级，供 server.py 代理使用

* 错误处理：启动失败写入 `user/artmirror/server.log` 并返回 None（代理路由返回 503 + 日志提示）。

### 5.3 `server.py` — aiohttp 反向代理

* 在 `PromptServer.instance` 注册：

  * `GET /artmirror` → 302 到 `/artmirror/gallery.html`

  * `GET/POST /artmirror/{tail:.*}` → 懒启动 embed（若未启动）→ `httpx` 异步转发 `http://127.0.0.1:{port}/{tail}`，流式回传 body、状态码与 Content-Type

* 覆盖方法：GET/POST/DELETE/PUT（ArtMirror 用到前三个）。

* 流式：使用 `aiohttp`/`httpx` 的流式响应，避免大文件（原图/缩略图）一次性载入内存。

* 代理路径仅做前缀剥离，不重写 body（前端相对路径在 `/artmirror/` 下自然解析）。

### 5.4 `web/artmirror-tab.js` — 前端扩展

```js
import { app } from "../../scripts/app.js";
app.registerExtension({
  name: "ArtMirror.Tab",
  async setup() {
    app.extensionManager.registerSidebarTab({
      id: "artmirror-gallery",
      title: "图库",
      type: "custom",
      render: (el) => {
        const iframe = document.createElement("iframe");
        iframe.src = "/artmirror/gallery.html";
        iframe.style.width = "100%";
        iframe.style.height = "100%";
        iframe.style.border = "0";
        el.appendChild(iframe);
      },
    });
  },
});
```

* 若 `registerSidebarTab` 在目标 ComfyUI 版本不可用，降级为 `registerBottomPanelTab`（实现相同）。

### 5.5 数据与运行目录

| 项        | 位置                                    | 说明                                  |
| -------- | ------------------------------------- | ----------------------------------- |
| SQLite 库 | `user/artmirror/artmirror.db`         | `folder_paths.get_user_directory()` |
| 缩略图      | `user/artmirror/thumbs/`              | 同 lib 同级                            |
| 日志       | `user/artmirror/server.log`           | uvicorn/logging 落盘                  |
| 默认扫描根    | `folder_paths.get_output_directory()` | Desktop 真实输出目录，用户可在设置页增删/改          |

* 图片仍只存引用（绝对路径 + sha256），不复制字节。

* LLM 配置沿用 ArtMirror 内嵌设置页 → 存 `settings` 表（插件 DB），独立版与插件各自独立。

### 5.6 依赖与发布

`pyproject.toml`：

```toml
[project]
name = "ComfyUI-ArtMirror"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "sqlmodel>=0.0.22",
  "pydantic-settings>=2.6",
  "pillow>=11.0",
  "httpx>=0.27",
  "python-multipart>=0.0.9",
  "send2trash>=1.8",
]

[tool.comfy]
PublisherId = "<registry 账号 id>"
DisplayName = "ArtMirror 图库"
Icon = "..."
Description = "ComfyUI 图片/提示词资产管理：图库浏览、workflow meta 解析、AI 反推/翻译/评分"
Version = "0.1.0"
```

* Manager 安装时自动 `pip install` 依赖（pillow/httpx 通常 ComfyUI 已有，幂等）。

* Registry 发布：`comfy node publish`（或 GitHub Actions 工作流），稳定版才可被 Desktop 一键安装。

* 前端同步：`sync_frontend.py` 把 ArtMirror `frontend/` 全量复制到 `static/`（无构建，复制即可），提交进插件仓库保证自包含。

## 6. ArtMirror 后端如何随插件分发

* 插件仓库**内含 ArtMirror 后端子包副本**：把 `backend/app` 复制为插件内 `artmirror_app/`（包名统一为 `artmirror_app`），`artmirror_embed.py` 改为 `from artmirror_app import main`。

* 提供 `sync_backend.py`（同 `sync_frontend.py`）从主仓库同步 `backend/app` → `artmirror_app/`，确保插件与独立版同源、可独立演进。

* 独立版 `app/config.py` 的默认 `data_dir`/`frontend_dir` 在插件场景下被 `artmirror_embed.py` **显式覆盖**（`settings.data_dir`、`settings.frontend_dir` 指向插件内位置），不依赖打包/冻结逻辑（此前的 exe 冻结方案已废弃）。

## 7. 错误处理与生命周期

| 场景          | 行为                                                    |
| ----------- | ----------------------------------------------------- |
| 首次打开「图库」tab | 懒启动线程；就绪前 iframe 显示加载态（前端扩展可加 polling 重载）             |
| embed 启动失败  | 代理返回 503 + 提示查看 `user/artmirror/server.log`           |
| ComfyUI 退出  | daemon 线程随进程结束，无残留；无需注册 shutdown 钩子                   |
| 节点刷新/重载     | 单例守卫保证不重复启动；端口已存在则复用                                  |
| 端口冲突        | 不存在：临时端口 + 同源代理，无外部端口暴露                               |
| 依赖缺失        | Manager 安装时 pip install；缺包导致 embed import 失败 → 日志明确提示 |

## 8. 测试策略

* **单测（后端逻辑）**：沿用 ArtMirror 现有 pytest（`config` 路径覆盖、API 层）迁移到插件内 `tests/`，验证 `data_dir`/扫描根覆盖逻辑与路由响应。

* **代理层测试**：`server.py` 的代理转发用 `aiohttp.test_utils`/pytest 对 `PromptServer` 的临时 app 起路由，指向一个测试后端，断言路径剥离与响应转发。

* **前端扩展**：按项目约定不做自动化浏览器验证；由用户在 ComfyUI 内强刷核对（iframe tab 出现、图库可用）。

* **手工冒烟**：在 ComfyUI（网页版或 Desktop）安装插件 → 侧边栏出现「图库」→ 能浏览输出目录图片、解析 meta、AI 功能可用、设置可保存。

* **回归**：独立版 `uv run pytest -q` 保持全绿（插件改动不触碰主仓库后端；若复用子包则同步覆盖）。

## 9. 发布流程（Comfy Registry）

1. 独立仓库 `ComfyUI-ArtMirror` 完成功能与测试
2. `pyproject.toml` 填 `[tool.comfy]`（PublisherId 等）
3. 本地 `comfy node publish --install-deps` 预检；或配置 GitHub Actions 自动发布
4. 发布 stable → Desktop「Manage Extensions」搜索安装验证
5. README 补：安装（Manager 搜索 / git clone 到 custom\_nodes）、使用（侧边栏「图库」tab）、独立版说明

## 10. 风险与缓解

| 风险                             | 缓解                                                     |
| ------------------------------ | ------------------------------------------------------ |
| 进程内 uvicorn 线程与 ComfyUI 事件循环竞争 | 独立线程 + 独立 asyncio loop，无共享 loop；代理用 httpx 异步转发         |
| 依赖冲突（sqlalchemy/send2trash 等）  | 均为独立包，ComfyUI 无同名运行依赖；安装失败由 Manager 暴露                 |
| `registerSidebarTab` 版本兼容      | 探测 API 存在性，降级 bottom panel；README 标注最低版本               |
| Desktop 更新覆盖插件                 | 插件在 `custom_nodes/`，数据在 `user/`，互不干扰                   |
| 大图/批量流式传输内存                    | 代理与缩略图/原图接口流式返回                                        |
| 前端与后端版本不同步                     | `sync_frontend.py`/`sync_backend.py` 双同步脚本 + README 说明 |
| 插件与独立版数据不互通                    | 明确两者各自独立 DB（独立版 `data/`，插件 `user/artmirror/`），不承诺互通    |

## 11. 范围外（YAGNI）

* 不做 ArtMirror 独立版与插件的数据双向同步/共享

* 不做 ComfyUI 前端深度定制（工作流节点渲染、出图后自动入库的实时钩子）——首版以「内嵌图库」为主；「出图自动入库」可作二期

* 不做 macOS/Linux 专属适配（跨平台通用，但只在 Windows 验证）

* 不做托盘、外部进程等多余形态

