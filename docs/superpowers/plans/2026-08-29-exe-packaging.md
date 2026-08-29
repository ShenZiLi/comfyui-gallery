# 画镜单文件 EXE 打包 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 PyInstaller 将画镜打包为单个 `画镜ArtMirror.exe`，小白双击静默启动、自动开浏览器、浏览器内一键关闭服务。

**Architecture:** `backend/run.py` 作为打包入口（程序化启动 uvicorn + 端口检测 + 开浏览器 + 日志落盘）；`config.py` 识别冻结态（`data/` 放 exe 旁、前端从 exe 内解出）；新增 `POST /api/shutdown` 优雅退出；前端加「关闭服务」按钮；`build/build.spec` + `build/build.ps1` 完成 PyInstaller onefile 构建。开发/本地运行（uv/启动.bat）保持不变。

**Tech Stack:** PyInstaller、Python venv、FastAPI/uvicorn（现有）、Pillow（生成 ico）。

**Spec:** `docs/superpowers/specs/2026-08-29-exe-packaging-design.md`

---

### Task 1: config.py 冻结态路径 + 单测

**Files:**
- Modify: `backend/app/config.py:16-17,29-31`
- Create: `backend/tests/test_config.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_config.py`：

```python
"""config.py 冻结态（PyInstaller）路径计算测试。"""
import sys
from pathlib import Path

import app.config as config_mod


def _fake_module_root():
    return Path("C:/proj")


def test_dev_paths(monkeypatch):
    """开发态：数据目录=项目根/data，前端=项目根/frontend。"""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(config_mod, "_module_root", _fake_module_root)
    assert config_mod._app_base_dir() == Path("C:/proj")
    assert config_mod._frontend_base_dir() == Path("C:/proj/frontend")


def test_frozen_paths(monkeypatch):
    """打包态：数据目录=exe 所在目录/data，前端=_MEIPASS/frontend。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:/exe/画镜ArtMirror.exe", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "C:/tmp/am_meipass", raising=False)
    assert config_mod._app_base_dir() == Path("C:/exe")
    assert config_mod._frontend_base_dir() == Path("C:/tmp/am_meipass/frontend")
```

- [ ] **Step 2: 运行确认失败**

运行：`cd backend; uv run pytest tests/test_config.py -v`
预期：FAIL（`AttributeError: module 'app.config' has no attribute '_app_base_dir'`）。

- [ ] **Step 3: 修改 config.py**

在 [config.py](file:///c:/Project/Code/ArtMirror/backend/app/config.py) 顶部 `from pathlib import Path` 之后追加：

```python
import sys


def _module_root() -> Path:
    """开发态项目根：backend/ 的父目录。"""
    return Path(__file__).resolve().parent.parent.parent


def _app_base_dir() -> Path:
    """运行数据基目录：打包态为 exe 所在目录（data/ 放 exe 旁，便携）；开发态为项目根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _module_root()


def _frontend_base_dir() -> Path:
    """前端静态资源目录：打包态为 exe 内解出的 frontend（sys._MEIPASS）；开发态为项目根/frontend。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "frontend"
    return _module_root() / "frontend"
```

再将两个字段默认值改为：

```python
    # 本地数据目录（SQLite 库、缩略图等）。打包态位于 exe 旁，开发态为项目根/data。
    data_dir: str = str(_app_base_dir() / "data")
```

```python
    frontend_dir: str = str(_frontend_base_dir())
```

- [ ] **Step 4: 运行确认通过**

运行：`cd backend; uv run pytest tests/test_config.py -v`
预期：2 passed。随后回归全量 `uv run pytest -q`，预期全部通过（11+ 例，原有测试不受影响）。

- [ ] **Step 5: 提交**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat: config 冻结态路径——打包态 data 放 exe 旁、前端从 _MEIPASS 解出"
```

---

### Task 2: 新增 POST /api/shutdown 后端 + 单测

**Files:**
- Create: `backend/app/routers/system.py`
- Modify: `backend/app/main.py:22,35-44`
- Create: `backend/tests/test_system_api.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_system_api.py`：

```python
"""系统路由测试：/api/shutdown 优雅关闭接口。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import system


class FakeServer:
    """模拟 uvicorn.Server：run.py 会把真实实例挂到 app.state.server。"""

    def __init__(self):
        self.should_exit = False


def _client(with_server=False):
    app = FastAPI()
    app.include_router(system.router)
    if with_server:
        app.state.server = FakeServer()
    return TestClient(app)


def test_shutdown_dev_mode():
    """开发态（无 server 实例）：返回 200 与开发提示，不报错。"""
    r = _client(False).post("/api/shutdown")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "开发模式" in r.json()["message"]


def test_shutdown_packaged_mode():
    """打包态（有 server 实例）：设置 should_exit=True 触发优雅退出。"""
    c = _client(True)
    server = c.app.state.server
    r = c.post("/api/shutdown")
    assert r.status_code == 200
    assert server.should_exit is True
```

- [ ] **Step 2: 运行确认失败**

运行：`cd backend; uv run pytest tests/test_system_api.py -v`
预期：FAIL（`ModuleNotFoundError: No module named 'app.routers.system'`）。

- [ ] **Step 3: 创建 system.py 并注册**

创建 `backend/app/routers/system.py`：

```python
"""系统级路由：目前仅「一键关闭服务」，供打包后的单文件 exe 使用。"""
from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.post("/api/shutdown")
def shutdown(request: Request) -> dict:
    """优雅关闭服务。

    打包态（run.py 启动）下，server 实例挂在 app.state.server 上，置
    should_exit=True 后 uvicorn 会响应完本次请求再退出，并触发 FastAPI
    shutdown 事件（watcher.stop()）。开发态（uvicorn CLI）下无该实例，
    返回提示而非关闭，避免误杀开发服务。
    """
    server = getattr(request.app.state, "server", None)
    if server is not None:
        server.should_exit = True
        return {"status": "ok", "message": "服务即将关闭，请稍候关闭此页面"}
    return {"status": "ok", "message": "开发模式请手动停止服务"}
```

修改 [main.py](file:///c:/Project/Code/ArtMirror/backend/app/main.py#L22)：

```python
from .routers import aggregate, folders, fs, images, settings as settings_router, sync, system, tags
```

修改 [main.py](file:///c:/Project/Code/ArtMirror/backend/app/main.py#L35-L44) 路由注册元组，末尾追加：

```python
    system.router,
```

- [ ] **Step 4: 运行确认通过**

运行：`cd backend; uv run pytest tests/test_system_api.py -v`
预期：2 passed。回归 `uv run pytest -q` 全绿。

- [ ] **Step 5: 提交**

```bash
git add backend/app/routers/system.py backend/tests/test_system_api.py backend/app/main.py
git commit -m "feat: POST /api/shutdown 优雅关闭服务（打包态）"
```

---

### Task 3: 新增 backend/run.py 打包入口 + 辅助函数单测

**Files:**
- Create: `backend/app/run_helpers.py`（可测试的纯函数，供 run.py 与单测复用）
- Create: `backend/run.py`
- Create: `backend/tests/test_run.py`

> 说明：`run.py` 位于 `backend/`（非 `app` 包内），项目 pytest 的 `pythonpath=["app"]` 无法直接 `import run`；故把可测辅助函数放在 `app/run_helpers.py`。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_run.py`：

```python
"""run.py 打包入口辅助函数测试（app/run_helpers.py）。"""
import socket
import tempfile
from pathlib import Path

from app.run_helpers import is_port_in_use, setup_file_logging


def test_is_port_in_use():
    """监听中的端口返回 True，关闭后返回 False。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.listen(1)
        assert is_port_in_use(port) is True
    assert is_port_in_use(port) is False


def test_setup_file_logging():
    """日志落盘到指定文件。"""
    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "server.log"
        setup_file_logging(log_path)
        assert log_path.exists()
```

- [ ] **Step 2: 运行确认失败**

运行：`cd backend; uv run pytest tests/test_run.py -v`
预期：FAIL（`ModuleNotFoundError: No module named 'app.run_helpers'`）。

- [ ] **Step 3: 创建 run_helpers.py 与 run.py**

创建 `backend/app/run_helpers.py`：

```python
"""打包入口 run.py 的可测试纯函数（端口检测 / 日志落盘）。"""
import logging
import socket
from pathlib import Path


def is_port_in_use(port: int) -> bool:
    """探测 127.0.0.1:port 是否已被监听。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def setup_file_logging(log_path: Path) -> None:
    """把日志重定向到文件（无控制台，必须有落盘日志便于排障）。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        encoding="utf-8",
    )
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
```

创建 `backend/run.py`（PyInstaller 入口；开发/本地仍用 `uvicorn app.main:app`）：

```python
"""画镜 ArtMirror 打包入口（PyInstaller 单文件 exe 使用）。

双击 exe 后：无窗口静默启动 uvicorn，日志落盘 data/server.log，
自动打开浏览器；浏览器内「关闭服务」按钮触发优雅退出。
开发/本地运行请使用 `uvicorn app.main:app`，本文件仅打包态使用。
"""
import logging
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from app.run_helpers import is_port_in_use, setup_file_logging

HOST = "0.0.0.0"
PORT = 8000
BASE_URL = f"http://127.0.0.1:{PORT}"
VERSION = "0.1.0"


def fatal_box(title: str, msg: str) -> None:
    """无控制台下用 MessageBox 弹窗提示致命错误。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, title, 0x10)  # MB_ICONERROR
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    from app import main as app_main
    from app.config import settings

    app = app_main.app
    settings.ensure_dirs()

    log_path = Path(settings.data_dir) / "server.log"
    setup_file_logging(log_path)
    log = logging.getLogger("run")

    if "--version" in sys.argv:
        log.info("画镜 ArtMirror %s (frozen=%s)", VERSION, bool(getattr(sys, "frozen", False)))
        return 0

    # 1) 端口已被占用 → 视为服务已在运行，直接打开浏览器后退出
    if is_port_in_use(PORT):
        log.info("端口 %s 已被占用，视为画镜已在运行，打开浏览器", PORT)
        webbrowser.open(f"{BASE_URL}/gallery.html")
        return 0

    # 2) 后台启动服务（日志已由 logging 落盘，uvicorn 不再输出到无控制台的 stderr）
    log.info("启动服务 %s:%s", HOST, PORT)
    server = uvicorn.Server(
        uvicorn.Config(app, host=HOST, port=PORT, log_config=None, access_log=False)
    )
    app.state.server = server
    thread = threading.Thread(target=server.run, daemon=True, name="uvicorn")
    thread.start()

    # 3) 轮询健康检查（最多约 60s）
    ready = False
    for _ in range(60):
        if server.should_exit:
            break
        try:
            with urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=2) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)

    if not ready:
        if server.should_exit:
            return 0
        fatal_box("画镜启动失败", f"服务启动超时或失败，请查看日志文件：\n{log_path}")
        log.error("服务启动失败：%s", log_path)
        return 1

    # 4) 打开浏览器进入图库
    log.info("服务就绪，打开浏览器")
    webbrowser.open(f"{BASE_URL}/gallery.html")

    # 5) 等待关闭：浏览器「关闭服务」→ POST /api/shutdown → server.should_exit=True
    while not server.should_exit:
        time.sleep(0.5)
    log.info("收到关闭信号，正在退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

> 说明：uvicorn 在非主线程运行 `server.run()` 时不会安装信号处理器（uvicorn 内部 `threading.current_thread() is threading.main_thread()` 判断），后台线程启动安全。

- [ ] **Step 4: 运行确认通过**

运行：`cd backend; uv run pytest tests/test_run.py -v`
预期：2 passed。
另跑 `uv run python run.py --version`，预期退出码 0 且 `data/server.log` 末尾出现 `画镜 ArtMirror 0.1.0 (frozen=False)` 日志行。

- [ ] **Step 5: 提交**

```bash
git add backend/app/run_helpers.py backend/run.py backend/tests/test_run.py
git commit -m "feat: 打包入口 run.py——程序化启动 uvicorn + 端口检测 + 开浏览器 + 日志落盘"
```

---

### Task 4: 前端「关闭服务」按钮

**Files:**
- Modify: `frontend/api.js`（在 `getSyncVersion` 前新增 `shutdown` 方法）
- Modify: `frontend/gallery.html`（工具栏加按钮 + Gallery 对象加 `shutdownService`）
- Modify: `frontend/settings.html`（新增「系统」卡片 + Settings 对象加 `shutdownService`）

> 前端改动按项目约定不做自动化浏览器验证，由用户强刷（Ctrl+Shift+R）核对。

- [ ] **Step 1: api.js 新增 shutdown**

在 [api.js](file:///c:/Project/Code/ArtMirror/frontend/api.js) 的 `getSyncVersion` 之前插入：

```js
    shutdown: function () {
      return req("api/shutdown", { method: "POST" }).catch(function (e) {
        throw (e && e.message) ? e : new Error("后端未连接");
      });
    },
```

- [ ] **Step 2: gallery.html 加按钮**

在 [gallery.html](file:///c:/Project/Code/ArtMirror/frontend/gallery.html#L84-L86) 的刷新按钮之后插入：

```html
      <!-- 关闭画镜服务（打包版：浏览器内一键停止） -->
      <button class="icon-btn danger" data-tip="关闭画镜服务" @click="shutdownService()">
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
      </button>
```

在 `window.Gallery` 对象内 [manualRefresh()](file:///c:/Project/Code/ArtMirror/frontend/gallery.html#L526) 方法之后追加：

```js
    shutdownService() {
      if (window.Api._fallback) { App.toast("离线模式，无需关闭"); return; }
      window.Api.shutdown().then(function (d) {
        App.toast((d && d.message) || "服务已关闭，可关闭此页面");
      }).catch(function () {
        App.toast("后端未连接，无需关闭");
      });
    },
```

- [ ] **Step 3: settings.html 加「系统」卡片与处理**

在 [settings.html](file:///c:/Project/Code/ArtMirror/frontend/settings.html#L181) 的「批量 AI 操作」卡片 `</div>` 之后、最外层 `</div>`（第 182 行）之前插入：

```html
    <!-- 系统 -->
    <div class="card pad">
      <h3 style="margin-top:0">系统</h3>
      <p class="muted">打包版（单文件 exe）下点击「关闭服务」会停止画镜；开发模式下请用终端停止。</p>
      <div class="btn-row mt">
        <button class="btn danger" @click="shutdownService()">关闭服务</button>
      </div>
    </div>
```

在 `window.Settings` 对象（[settings.html](file:///c:/Project/Code/ArtMirror/frontend/settings.html#L203)）内 `init` 方法之后追加：

```js
    shutdownService() {
      if (window.Api._fallback) { App.toast("离线模式，无需关闭"); return; }
      window.Api.shutdown().then(function (d) {
        App.toast((d && d.message) || "服务已关闭，可关闭此页面");
      }).catch(function () {
        App.toast("后端未连接，无需关闭");
      });
    },
```

- [ ] **Step 4: 校验**

- `Select-String -Path "frontend\api.js" -Pattern "shutdown:"` 命中
- `Select-String -Path "frontend\gallery.html","frontend\settings.html" -Pattern "shutdownService"` 命中
- 语法自检：确认 `.then/.catch` 配平、逗号分隔正确（Alpine 对象方法间用 `,`）。

- [ ] **Step 5: 提交**

```bash
git add frontend/api.js frontend/gallery.html frontend/settings.html
git commit -m "feat: 浏览器内一键关闭服务按钮（图库顶栏 + 设置页）"
```

---

### Task 5: PyInstaller 构建（spec + 脚本 + 实际构建）

**Files:**
- Modify: `backend/pyproject.toml`（dev 组加 `pyinstaller>=6.0`）
- Create: `build/build.spec`
- Create: `build/build.ps1`

- [ ] **Step 1: pyproject 加 PyInstaller**

修改 [pyproject.toml](file:///c:/Project/Code/ArtMirror/backend/pyproject.toml#L17-L21)：

```toml
[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pyinstaller>=6.0",
]
```

运行：`cd backend; uv sync`（安装 pyinstaller 到开发环境）。

- [ ] **Step 2: 创建 build/build.spec**

创建 `build/build.spec`（PyInstaller 在 build/ 目录运行，`SPECPATH` 指向 build/）：

```python
# -*- mode: python ; coding: utf-8 -*-
"""画镜 ArtMirror 单文件 exe 打包配置。在 build/ 下由 build.ps1 调用。"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent  # 项目根（build.spec 位于 build/）
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ICON = ROOT / "build" / "icon.ico"

a = Analysis(
    [str(BACKEND / "run.py")],
    pathex=[str(BACKEND)],
    binaries=[],
    datas=[(str(FRONTEND), "frontend")],
    hiddenimports=[
        "sqlmodel", "pydantic", "multipart", "send2trash", "send2trash.win",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# 兜底收集 uvicorn 全量子模块（动态导入易遗漏）
for pkg in ("uvicorn", "fastapi", "starlette"):
    _d, _b, _h = collect_all(pkg)
    a.datas += _d
    a.binaries += _b
    a.hiddenimports += _h

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="画镜ArtMirror",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,            # 无窗口静默运行
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
)
```

- [ ] **Step 3: 创建 build/build.ps1**

创建 `build/build.ps1`（自举：确保 pyinstaller、生成 ico、打包）：

```powershell
# 画镜 ArtMirror 一键打包：build/build.ps1 → dist/画镜ArtMirror.exe
$ErrorActionPreference = "Stop"
$BuildDir = Split-Path -Parent $MyInvocation.MyCommand.Path   # build/
$Proj = Split-Path -Parent $BuildDir                          # 项目根
$VenvPy = Join-Path $Proj "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $VenvPy)) {
    Write-Host "未找到 backend\.venv，请先运行 uv sync 或 启动.bat。"
    exit 1
}

# 1) 确保 pyinstaller
& $VenvPy -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "安装 pyinstaller…"
    & $VenvPy -m pip install --disable-pip-version-check -q "pyinstaller>=6.0"
    if ($LASTEXITCODE -ne 0) { Write-Host "pyinstaller 安装失败"; exit 1 }
}

# 2) 用品牌 512 图生成多尺寸 icon.ico
$iconSrc = Join-Path $Proj "frontend\assets\icons\icon-512.png"
$iconOut = Join-Path $BuildDir "icon.ico"
if (-not (Test-Path $iconOut)) {
    & $VenvPy -c @"
from PIL import Image
im = Image.open(r'$iconSrc').convert('RGBA')
im.save(r'$iconOut', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
print('icon ->', r'$iconOut')
"@
}

# 3) 打包（在 build/ 下执行，spec 内路径相对 SPECPATH）
Push-Location $BuildDir
& $VenvPy -m PyInstaller --noconfirm --clean "build.spec"
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Write-Host "PyInstaller 构建失败"; exit 1 }

# 4) 校验产物
$exe = Join-Path $BuildDir "dist\画镜ArtMirror.exe"
if (-not (Test-Path $exe)) { Write-Host "构建完成但未找到产物：$exe"; exit 1 }
$size = (Get-Item $exe).Length / 1MB
Write-Host ("打包完成：{0}（{1:N1} MB）" -f $exe, $size)
```

- [ ] **Step 4: 实际构建验证**

运行：`powershell -NoProfile -ExecutionPolicy Bypass -File build\build.ps1`
预期：输出「打包完成：...dist\画镜ArtMirror.exe（约 xx MB）」，`dist/画镜ArtMirror.exe` 存在。
> 若构建环境有误报/网络问题导致失败，记录错误信息并反馈，不强行重试超过 2 次。

- [ ] **Step 5: 提交**

```bash
git add backend/pyproject.toml build/build.spec build/build.ps1 build/icon.ico
git commit -m "feat: PyInstaller 打包配置与一键构建脚本（build.ps1）"
```

---

### Task 6: 文档（README + 功能清单）

**Files:**
- Modify: `README.md`（新增「绿色版单文件 exe」章节）
- Modify: `docs/功能清单.md`（补记功能点 + 更新记录）

- [ ] **Step 1: README 新增章节**

在 README 的「小白快速启动（Windows）」章节之后插入：

```markdown
## 绿色版单文件 exe（Windows）

不想装 Python 的环境，可直接使用打包好的单文件 exe：

1. 将 `画镜ArtMirror.exe` 放到任意**可写目录**（如桌面、D 盘；勿放 Program Files）
2. 双击运行 → 无窗口静默启动 → 自动打开浏览器进入图库
3. 停止服务：在浏览器 **设置页 → 系统 → 关闭服务**（或图库顶栏「关闭」按钮）

说明：

- 运行数据（数据库/缩略图）自动生成在 **exe 旁 `data/` 文件夹**，拷贝 `exe + data/` 即可整体迁移
- 重复双击不会重复启动：端口被占用时视为已在运行，仅重新打开浏览器
- 首次运行若被 Windows SmartScreen 提示「未知发布者」：点 **更多信息 → 仍要运行**；如被杀软拦截请加入白名单（未做付费代码签名）
- 启动解包约 1-3 秒属正常现象
- 构建方式：运行 `build/build.ps1`（需 Python + PyInstaller），产物在 `dist/画镜ArtMirror.exe`
```

- [ ] **Step 2: 功能清单补记**

在 [功能清单.md](file:///c:/Project/Code/ArtMirror/docs/功能清单.md) 的「### 部署 / 启动」小节追加：

```markdown
* [x] 单文件 EXE 绿色版：PyInstaller onefile 打包 `画镜ArtMirror.exe`，双击静默启动、自动开浏览器、浏览器内一键关闭服务；运行数据落 exe 旁 `data/`；`build/build.ps1` 一键构建
```

并在「更新记录」表首行追加：

```markdown
| 2026-08-29 | 单文件 EXE 绿色版         | 新增：PyInstaller onefile 打包 `dist/画镜ArtMirror.exe`（--noconsole 静默运行）；`config.py` 冻结态路径（data 放 exe 旁、前端从 _MEIPASS 解出）；`backend/run.py` 打包入口（程序化 uvicorn + 端口检测 + 开浏览器 + 日志落盘 + 致命错误弹窗）；`POST /api/shutdown` 优雅关闭 + 图库/设置页「关闭服务」按钮；`build/build.spec` + `build/build.ps1` 一键构建；README 新增绿色版章节 |
```

- [ ] **Step 3: 校验并提交**

运行：`Select-String -Path "README.md" -Pattern "绿色版单文件"`，命中即通过。

```bash
git add README.md docs/功能清单.md
git commit -m "docs: 绿色版单文件 exe 章节与功能清单补记"
```

---

### Task 7: 端到端核对

**Files:** 无新增

- [ ] **Step 1: 回归测试**

运行：`cd backend; uv run pytest -q`
预期：全部通过（含新增 test_config / test_system_api / test_run，原有用例不受影响）。

- [ ] **Step 2: 核对产物与关键文件**

运行：

```powershell
Test-Path "C:\Project\Code\ArtMirror\dist\画镜ArtMirror.exe"
Test-Path "C:\Project\Code\ArtMirror\build\build.spec"
Test-Path "C:\Project\Code\ArtMirror\backend\run.py"
Select-String -Path "C:\Project\Code\ArtMirror\backend\app\main.py" -Pattern "system.router"
```

预期：三个 True + 命中。

- [ ] **Step 3: 核对打包态路径与关闭链路**

- `uv run python run.py --version` → 退出码 0，`data/server.log` 出现 `画镜 ArtMirror 0.1.0 (frozen=False)`
- 启动开发服务后 `curl -X POST http://127.0.0.1:8000/api/shutdown` → 返回 `{"status":"ok","message":"开发模式请手动停止服务"}`（开发态不误杀）
- 核对 `config.py`：`_app_base_dir`/`_frontend_base_dir` 冻结分支与 spec 的 `sys._MEIPASS` 一致

- [ ] **Step 4: 提交（若 Task 1-6 均已提交则跳过）**

---

## Self-Review

* **Spec 覆盖**：冻结态路径（Task 1）、`POST /api/shutdown`（Task 2）、`run.py` 入口 + 端口检测 + 开浏览器 + 日志 + 弹窗（Task 3）、前端关闭按钮（Task 4）、PyInstaller spec/脚本/图标（Task 5）、README + 功能清单（Task 6）、端到端核对（Task 7）—— 全覆盖。
* **占位符**：无 TBD/TODO，所有步骤给出完整代码与预期输出。
* **类型一致性**：`is_port_in_use`/`setup_file_logging`（Task 3 定义与测试一致）；`Api.shutdown()`（Task 4 api.js）与 `window.Api.shutdown()` 调用一致；`app.state.server` 由 run.py 挂载、system.py 读取、main.py 注册路由，三者一致；`build/build.ps1` 调用的 `build.spec` 文件名一致。
* **风险**：PyInstaller 构建若受环境/网络影响失败，Task 5 已明确不强行重试超 2 次并反馈；前端改动不做自动化浏览器验证（项目约定）。
