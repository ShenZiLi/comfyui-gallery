# 画镜 ArtMirror 单文件 EXE 分发设计

> 日期：2026-08-29 ｜ 状态：待审阅 ｜ 面向小白分发的 Windows 单文件绿色版

## 1. 目标

将画镜打包为**单个** `画镜ArtMirror.exe`（Windows），小白**双击即可静默运行**并自动打开浏览器进入图库，无需安装 Python/任何依赖。

## 2. 已确认决策（与用户逐项对齐）

| 决策点    | 选择                                          |
| ------ | ------------------------------------------- |
| 交付目标   | 分发给别人（小白向）                                  |
| 打包工具   | **PyInstaller onefile**（方案 A）               |
| 运行数据位置 | **exe 旁自动建** **`data/`**（便携式）               |
| 运行形态   | **无窗口静默运行**，双击自动开浏览器                        |
| 停止方式   | **浏览器内一键关闭**（设置页 + 图库顶栏按钮 → 后端 shutdown 接口） |

## 3. 约束与前提

* **「单文件零残留」不可行**：SQLite 库 + 缩略图必须写盘。约定：exe 运行时在自身所在目录自动创建 `data/`（`artmirror.db` + `thumbs/`），退出不清空 → 便携、整体拷贝 `exe + data/` 即可迁移。

* **图片不打包**：图库只存 `abs_path` 引用、不存字节，exe 体积可控；目标机器上由用户在设置页注册自己的图片目录（沿用现有功能）。

* **LLM 配置存于 DB**（settings 表），各机器各自配置，不受打包影响。

* **保留现有链路**：`uv` / `启动.bat` / `start.ps1` 仍是开发与本地运行方式，入口同为 `app.main:app`；exe 仅为额外分发产物，互不干扰。

* **勿放受保护目录**：exe 不应放入 Program Files 等写受限目录（否则 `data/` 创建失败）；README 提示。

* **SmartScreen/杀软可能误报「未知发布者」**：不付费代码签名；README 给出「更多信息 → 仍要运行」指引与加白名单建议。

## 4. 架构

```
画镜ArtMirror.exe（PyInstaller onefile，--noconsole）
  ├── Python 3.11 运行时 + 全部依赖（fastapi/uvicorn/sqlmodel/pillow/...）
  ├── frontend/   静态资源（打包进 exe，运行时由 sys._MEIPASS 解出）
  └── backend/app 业务代码
```

**运行链路（双击后）**：

1. 冻结态识别（`sys.frozen`）：`data_dir` → **exe 同目录** **`/data`**；`frontend_dir` → `sys._MEIPASS/frontend`
2. 端口检测：8000 已被占用 → 视为已在运行 → 打开浏览器 → 退出
3. 后台线程启动 `uvicorn.Server`（实例挂到 `app.state.server`）；日志重定向落盘 `data/server.log`（无控制台，必须有日志）
4. 主线程轮询 `/api/health` → 就绪后 `webbrowser.open(gallery.html)`
5. 浏览器「关闭服务」→ `POST /api/shutdown` → `server.should_exit = True` → uvicorn 优雅退出（触发 FastAPI shutdown，`watcher.stop()`）→ 进程结束
6. 致命错误：`ctypes.windll.user32.MessageBoxW` 弹窗提示（无窗口下小白也能看到问题）

## 5. 组件与改动

### 5.1 新增 `backend/run.py`（打包入口）

PyInstaller 入口脚本（替代 `uvicorn app.main:app` 命令行），职责：

* 导入 `app.main:app`（模块全局 `app`）

* 端口占用检测（socket bind 探测 8000）：占用 → `webbrowser.open` → `sys.exit(0)`

* 构造 `uvicorn.Config(app, host="0.0.0.0", port=8000, log_config=<落盘 dictConfig>)`

* 创建 `uvicorn.Server(config)`，挂到 `app.state.server`

* 后台线程 `threading.Thread(target=server.run, daemon=True)`（uvicorn 在非主线程不装信号处理器，安全）

* 主线程轮询 `/api/health`（超时 \~60s），就绪后 `webbrowser.open("http://127.0.0.1:8000/gallery.html")`

* 等待 `server.should_exit`（shutdown 接口触发）→ 进程退出

* 启动失败/超时/依赖异常：写日志 + MessageBoxW 弹窗

* 支持 `--version` 打印版本（便于核对打包产物）

### 5.2 修改 `backend/app/config.py`：冻结态路径

模块级新增两个辅助函数：

```python
def _app_base_dir() -> Path:
    """打包态：exe 所在目录；开发态：项目根（backend/..）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent

def _frontend_base_dir() -> Path:
    """打包态：exe 内解出的 frontend（_MEIPASS）；开发态：项目根/frontend。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "frontend"
    return Path(__file__).resolve().parent.parent.parent / "frontend"
```

* `data_dir` 默认值 → `_app_base_dir() / "data"`

* `frontend_dir` 默认值 → `_frontend_base_dir()`

* 保留 `.env` / `AM_*` 环境变量覆盖能力

* 辅助函数做成可单测的纯函数（参数化 frozen/exe 路径，便于 monkeypatch 断言）

### 5.3 新增 `POST /api/shutdown`

* 路由：`POST /api/shutdown` → `{"status":"ok","message":"服务即将关闭"}`

* 逻辑：`server = getattr(app.state, "server", None)`；非空 → `server.should_exit = True`

* 响应先返回，uvicorn 随后优雅退出（触发 `watcher.stop()`）

* 开发态（uvicorn CLI）下 `app.state.server` 不存在 → 返回 `{"status":"ok","message":"开发模式请手动停止"}`，不报错

* 归属：并入现有 routers（建议 `settings` 路由或新建 `system` 路由）

### 5.4 前端「关闭服务」按钮

* **settings.html**：新增「系统」小节，一个红色警示「关闭服务」按钮；点击 → `Api.shutdown()` → 成功 toast「服务已关闭，可关闭此页面」并禁用按钮；失败提示

* **gallery.html**：顶栏操作区新增「关闭」按钮（`data-tip` 气泡「关闭画镜服务」）；同样调 `Api.shutdown()`

* **api.js**：新增 `Api.shutdown()` → `POST /api/shutdown`

* 离线/mock 态：接口不可用 → 按钮提示「后端未连接，无需关闭」；mock 模式隐藏或提示

### 5.5 PyInstaller 构建产物

* 新增 `build/build.spec`（在 `build/` 下执行，路径相对 spec 文件）：

  * `Analysis(['../backend/run.py'], ...)`；`--collect-all uvicorn`、`--collect-all sqlmodel` 等隐藏依赖兜底

  * `datas`: `('../frontend', 'frontend')`、`('icon.ico', '.')`

  * `EXE(..., name='画镜ArtMirror', console=False, icon='build/icon.ico')`

* 新增 `build/build.ps1`：

  * 复用 `backend/.venv`（或 `uv run`），dev 组含 `pyinstaller`

  * 用 Pillow 从 `frontend/assets/icons/icon-512.png` 生成 `build/icon.ico`（多尺寸 16..256）

  * 执行 `pyinstaller build/build.spec --noconfirm --clean`

  * 产物 `dist/画镜ArtMirror.exe`，打印体积

* `backend/pyproject.toml` dev 组新增 `pyinstaller>=6.0`

### 5.6 文档

* **README.md** 新增「绿色版单文件 exe」章节：

  * 使用：双击 → 自动开浏览器 → 浏览器内「关闭服务」停止

  * 数据目录：exe 旁 `data/`，整体拷贝即迁移；勿放 Program Files

  * SmartScreen/杀软误报指引（更多信息→仍要运行 / 加白名单）

  * 端口 8000 占用说明（重复双击直接开浏览器）

* **docs/功能清单.md**：补记功能点 + 更新记录

### 5.7 测试

* pytest 新增：

  * `config` 冻结态路径计算（monkeypatch `sys.frozen`/`sys.executable`/`_MEIPASS` → 断言 data\_dir 指向 exe 旁、frontend\_dir 指向 \_MEIPASS/frontend）

  * `POST /api/shutdown` 返回 ok 且不抛错（TestClient，含开发态无 server 场景）

* 构建验证：运行 `build/build.ps1` → `dist/画镜ArtMirror.exe` 存在；`--version` 写日志确认打包完整（沙箱不做浏览器自动化验证，前端改动由用户强刷核对）

* 回归：`uv run pytest -q` 全绿；现有 `uv`/`启动.bat` 路径不受影响

## 6. 风险与缓解

| 风险                   | 缓解                                      |
| -------------------- | --------------------------------------- |
| SmartScreen「未知发布者」   | README 指引「更多信息→仍要运行」；暂不签名               |
| onefile 启动慢（解包 1-3s） | 可接受；README 说明属正常                        |
| 杀软误报删除 exe           | README 建议加白名单/排除项                       |
| 冻结态路径算错致数据丢失         | 单测覆盖；data\_dir 只依赖 exe 位置，稳定            |
| 无控制台排障难              | 日志落盘 `data/server.log`；致命错误弹 MessageBox |
| 端口被其它程序占用            | 与 start.ps1 一致：直接开浏览器；健康检查兜底            |

## 7. 范围外（YAGNI）

* 不做代码签名、自动更新、多语言、便携 ZIP 自解压

* 不做 macOS / Linux 打包（仅 Windows）

* 不做托盘图标方案（用户已选择浏览器内关闭）

<br />
