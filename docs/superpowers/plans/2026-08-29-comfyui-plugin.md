# ArtMirror × ComfyUI 插件实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把画镜 ArtMirror 打包为 ComfyUI 自定义节点包，在 ComfyUI 侧边栏内嵌「图库」tab，后端经 `/artmirror/*` aiohttp 反向代理到进程内 FastAPI，功能与独立版对齐，可发布 Comfy Registry。

**Architecture:** ComfyUI 进程内用后台线程跑 uvicorn（FastAPI，监听 127.0.0.1 临时端口），在 PromptServer 挂 `/artmirror/*` 反向代理路由；前端扩展注册侧边栏 tab 用 iframe 加载 `/artmirror/gallery.html`；`backend/app` 与 `frontend/` 通过同步脚本复制为插件内 `artmirror_app/` 与 `static/`，后端零改动。

**Tech Stack:** ComfyUI 自定义节点（aiohttp + Python）+ 进程内 uvicorn/FastAPI + SQLModel(SQLite) + 前端 JS 扩展。

**Spec:** `docs/superpowers/specs/2026-08-29-comfyui-plugin-design.md`

**开发位置说明**：插件代码位于本仓库 `comfyui-plugin/` 子目录（沙箱限制无法在仓库外建目录）；该目录结构 1:1 对应未来独立仓库 `ComfyUI-ArtMirror`，完成后可用 `git subtree split` 拆出独立仓库发布 Registry。

---

### Task 1: 插件脚手架（目录 + pyproject + 占位节点 + README）

**Files:**
- Create: `comfyui-plugin/pyproject.toml`
- Create: `comfyui-plugin/__init__.py`
- Create: `comfyui-plugin/.gitignore`
- Create: `comfyui-plugin/README.md`

- [ ] **Step 1: 创建 pyproject.toml**

内容（依赖与 ArtMirror 后端一致；`[tool.comfy]` 为 Registry 发布元数据）：

```toml
[project]
name = "ComfyUI-ArtMirror"
version = "0.1.0"
description = "画镜 ArtMirror：ComfyUI 图片/提示词资产管理（图库浏览、workflow meta 解析、AI 反推/翻译/评分）"
requires-python = ">=3.11"
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

[project.optional-dependencies]
test = ["pytest>=8.3", "aiohttp>=3.9"]

[tool.comfy]
PublisherId = "shenzili"  # 发布前改为你的 Comfy Registry 账号 ID
DisplayName = "ArtMirror 图库"
Icon = ""
Description = "画镜 ArtMirror：ComfyUI 图片/提示词资产管理（图库浏览、workflow meta 解析、AI 反推/翻译/评分）"
Version = "0.1.0"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 2: 创建 __init__.py**

内容（占位节点 + `WEB_DIRECTORY` + 惰性挂载路由；非 ComfyUI 环境静默跳过）：

```python
"""ComfyUI-ArtMirror：画镜 ArtMirror 图库插件。"""
import logging

log = logging.getLogger("artmirror.plugin")

# 前端扩展目录（WEB_DIRECTORY 仅服务 .js，HTML 前端由后端路由托管）
WEB_DIRECTORY = "web"


class ArtMirrorLauncher:
    """占位节点：使包被 ComfyUI 识别为自定义节点包（NODE_CLASS_MAPPINGS 非空）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ()
    FUNCTION = "noop"
    CATEGORY = "ArtMirror"

    def noop(self):
        return ()


NODE_CLASS_MAPPINGS = {"ArtMirrorLauncher": ArtMirrorLauncher}
NODE_DISPLAY_NAME_MAPPINGS = {"ArtMirrorLauncher": "ArtMirror 图库"}


def _register_routes():
    """挂载 /artmirror/* 路由（懒加载：仅 ComfyUI 环境可用时）。"""
    try:
        from . import server as _server
        _server.register_proxy_routes()
    except Exception:  # noqa: BLE001
        log.warning("ArtMirror 路由未挂载（非 ComfyUI 环境）", exc_info=True)


_register_routes()
```

- [ ] **Step 3: 创建 .gitignore**

```gitignore
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
```

- [ ] **Step 4: 创建 README.md**

```markdown
# ComfyUI-ArtMirror 画镜图库

在 ComfyUI 侧边栏内嵌「图库」tab：浏览/管理 ComfyUI 输出图片，解析内嵌 workflow meta，AI 反推/中英翻译/评分（功能与独立版画镜一致）。

## 安装

- **ComfyUI-Manager / Desktop**：搜索 `ArtMirror 图库` 一键安装（发布到 Registry 后）
- **手动**：`git clone` 到 `custom_nodes/`，重启 ComfyUI

## 使用

安装后侧边栏出现「图库」tab；首次打开自动启动后端并扫描 ComfyUI 输出目录。设置页（tab 内）可改扫描目录、配置大模型（LLM）启用 AI 功能。

## 数据

数据库/缩略图/日志位于 ComfyUI `user/artmirror/`；默认扫描根为 ComfyUI 输出目录。
```

- [ ] **Step 5: 验证**

- `Test-Path comfyui-plugin/pyproject.toml` 等四文件存在
- 目录可被 pytest 识别（后续任务会用到 `pythonpath=["."]`）

- [ ] **Step 6: 提交**

```bash
git add comfyui-plugin/
git commit -m "feat: ComfyUI 插件脚手架（pyproject/占位节点/README）"
```

---

### Task 2: 后端同步脚本 + artmirror_app 子包

**Files:**
- Create: `comfyui-plugin/sync_backend.py`
- Create: `comfyui-plugin/artmirror_app/__init__.py`（由脚本生成，含一句说明）
- Test: `comfyui-plugin/tests/test_sync_backend.py`

- [ ] **Step 1: 写失败测试**

创建 `comfyui-plugin/tests/test_sync_backend.py`：

```python
"""后端同步脚本验证：artmirror_app 可导入且含 main.app。"""
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent


def test_artmirror_app_importable():
    """artmirror_app 包存在且可导入 app.main（同步脚本已运行）。"""
    import artmirror_app
    from artmirror_app import main
    assert hasattr(main, "app")


def test_sync_script_updates_copy():
    """重跑同步脚本后 artmirror_app 与 backend/app 文件清单一致。"""
    result = subprocess.run(
        [sys.executable, str(PLUGIN / "sync_backend.py")],
        capture_output=True, text=True, cwd=str(PLUGIN.parent),
    )
    assert result.returncode == 0, result.stderr
    src = set(p.name for p in (PLUGIN.parent / "backend" / "app").rglob("*.py") if "__pycache__" not in str(p))
    dst = set(p.name for p in (PLUGIN / "artmirror_app").rglob("*.py") if "__pycache__" not in str(p))
    assert dst >= src
```

- [ ] **Step 2: 运行确认失败**

运行：`..\backend\.venv\Scripts\python.exe -m pytest comfyui-plugin\tests\test_sync_backend.py -q`
预期：FAIL（`ModuleNotFoundError: No module named 'artmirror_app'`）。

- [ ] **Step 3: 创建 sync_backend.py**

创建 `comfyui-plugin/sync_backend.py`：

```python
"""把 ArtMirror 主仓库 backend/app 同步为插件内 artmirror_app/。

用法：python sync_backend.py（需在插件目录或仓库根执行，脚本自动定位）。
"""
import shutil
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent
REPO = PLUGIN.parent
SRC = REPO / "backend" / "app"
DST = PLUGIN / "artmirror_app"

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def main() -> int:
    if not SRC.is_dir():
        print(f"未找到 {SRC}")
        return 1
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST, ignore=_IGNORE)
    # 标识这是同步副本
    (DST / "__init__.py").write_text(
        '"""ArtMirror 后端（由 sync_backend.py 从主仓库同步，勿手改）。"""\n',
        encoding="utf-8",
    )
    print(f"已同步 {SRC} -> {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行同步 + 确认通过**

运行：`..\backend\.venv\Scripts\python.exe comfyui-plugin\sync_backend.py`
预期：输出「已同步 ... backend/app -> ... artmirror_app」。
再运行测试：`..\backend\.venv\Scripts\python.exe -m pytest comfyui-plugin\tests\test_sync_backend.py -q`
预期：2 passed。

- [ ] **Step 5: 提交**

```bash
git add comfyui-plugin/sync_backend.py comfyui-plugin/artmirror_app comfyui-plugin/tests
git commit -m "feat: 后端同步脚本 + artmirror_app 子包"
```

---

### Task 3: comfy_paths 适配器 + 单测

**Files:**
- Create: `comfyui-plugin/comfy_paths.py`
- Test: `comfyui-plugin/tests/test_comfy_paths.py`

- [ ] **Step 1: 写失败测试**

创建 `comfyui-plugin/tests/test_comfy_paths.py`：

```python
"""ComfyUI 路径适配器测试（可注入，脱离 ComfyUI 运行）。"""
import comfy_paths


def test_set_paths_override():
    """显式注入路径后，get_user_dir/get_output_dir 返回注入值。"""
    comfy_paths.set_paths("C:/u", "C:/out")
    assert comfy_paths.get_user_dir() == "C:/u"
    assert comfy_paths.get_output_dir() == "C:/out"


def test_fallback_defaults():
    """未注入且无 ComfyUI 时回退到 ~/ComfyUI。"""
    comfy_paths.set_paths(None, None)
    assert comfy_paths.get_user_dir().endswith("ComfyUI/user")
    assert comfy_paths.get_output_dir().endswith("ComfyUI/output")
```

- [ ] **Step 2: 运行确认失败**

运行：`..\backend\.venv\Scripts\python.exe -m pytest comfyui-plugin\tests\test_comfy_paths.py -q`
预期：FAIL（`ModuleNotFoundError: No module named 'comfy_paths'`）。

- [ ] **Step 3: 创建 comfy_paths.py**

创建 `comfyui-plugin/comfy_paths.py`：

```python
"""ComfyUI 目录路径适配器。

真实环境优先用 ComfyUI 的 folder_paths；未安装（单测/独立运行）时回退，
也可用 set_paths 显式注入。
"""
import os

_user_dir = None
_output_dir = None


def set_paths(user_dir, output_dir):
    """显式注入路径（测试与特殊部署用）。"""
    global _user_dir, _output_dir
    _user_dir = user_dir
    _output_dir = output_dir


def _folder_paths():
    try:
        import folder_paths
        return folder_paths
    except Exception:  # noqa: BLE001
        return None


def get_user_dir() -> str:
    if _user_dir:
        return _user_dir
    fp = _folder_paths()
    if fp is not None:
        return fp.get_user_directory()
    return os.path.join(os.path.expanduser("~"), "ComfyUI", "user")


def get_output_dir() -> str:
    if _output_dir:
        return _output_dir
    fp = _folder_paths()
    if fp is not None:
        return fp.get_output_directory()
    return os.path.join(os.path.expanduser("~"), "ComfyUI", "output")
```

- [ ] **Step 4: 运行确认通过**

运行：`..\backend\.venv\Scripts\python.exe -m pytest comfyui-plugin\tests\test_comfy_paths.py -q`
预期：2 passed。

- [ ] **Step 5: 提交**

```bash
git add comfyui-plugin/comfy_paths.py comfyui-plugin/tests/test_comfy_paths.py
git commit -m "feat: comfy_paths 路径适配器（folder_paths/回退/注入）"
```

---

### Task 4: artmirror_embed 进程内 uvicorn 线程 + 单测

**Files:**
- Create: `comfyui-plugin/artmirror_embed.py`
- Test: `comfyui-plugin/tests/test_artmirror_embed.py`

- [ ] **Step 1: 写失败测试**

创建 `comfyui-plugin/tests/test_artmirror_embed.py`：

```python
"""进程内 ArtMirror 启动线程测试。"""
import tempfile
from pathlib import Path

import httpx

import artmirror_embed
import comfy_paths


def test_start_and_health():
    """start() 返回可用端口，/api/health 可访问，stop() 后端口释放。"""
    with tempfile.TemporaryDirectory() as td:
        comfy_paths.set_paths(str(Path(td) / "user"), str(Path(td) / "out"))
        port = artmirror_embed.start()
        assert isinstance(port, int) and port > 0
        r = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=5)
        assert r.status_code == 200
        assert r.json()["app"] == "artmirror"
        assert artmirror_embed.get_url() == f"http://127.0.0.1:{port}"
        artmirror_embed.stop()
        assert artmirror_embed.get_url() is None


def test_start_singleton():
    """重复 start() 返回同一端口，不重复启动。"""
    with tempfile.TemporaryDirectory() as td:
        comfy_paths.set_paths(str(Path(td) / "user"), str(Path(td) / "out"))
        p1 = artmirror_embed.start()
        p2 = artmirror_embed.start()
        assert p1 == p2
        artmirror_embed.stop()
```

- [ ] **Step 2: 运行确认失败**

运行：`..\backend\.venv\Scripts\python.exe -m pytest comfyui-plugin\tests\test_artmirror_embed.py -q`
预期：FAIL（`ModuleNotFoundError: No module named 'artmirror_embed'`）。

- [ ] **Step 3: 创建 artmirror_embed.py**

创建 `comfyui-plugin/artmirror_embed.py`：

```python
"""在 ComfyUI 进程内以后台线程运行 ArtMirror FastAPI（临时端口）。"""
import logging
import threading
import time
from pathlib import Path

import uvicorn

from . import comfy_paths

log = logging.getLogger("artmirror.embed")

_state = {"lock": threading.Lock(), "server": None, "port": None}


def resolve_data_dir() -> str:
    return str(Path(comfy_paths.get_user_dir()) / "artmirror")


def resolve_frontend_dir() -> str:
    return str(Path(__file__).resolve().parent / "static")


def _configure(settings) -> None:
    settings.data_dir = resolve_data_dir()
    settings.frontend_dir = resolve_frontend_dir()
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)


def start() -> int | None:
    """启动 ArtMirror（单例）。成功返回端口，失败返回 None。"""
    with _state["lock"]:
        if _state["port"] is not None:
            return _state["port"]
        try:
            from artmirror_app import main as app_main
            from artmirror_app.config import settings

            _configure(settings)
            settings.ensure_dirs()

            server = uvicorn.Server(
                uvicorn.Config(app_main.app, host="127.0.0.1", port=0,
                               log_config=None, access_log=False)
            )
            thread = threading.Thread(target=server.run, daemon=True, name="artmirror")
            thread.start()

            port = None
            for _ in range(100):
                if server.servers and server.servers[0].sockets:
                    port = server.servers[0].sockets[0].getsockname()[1]
                    break
                time.sleep(0.05)
            if port is None:
                log.error("ArtMirror 启动失败：未获取到监听端口")
                return None

            _state["server"] = server
            _state["port"] = port
            log.info("ArtMirror 就绪 http://127.0.0.1:%s", port)
            return port
        except Exception as exc:  # noqa: BLE001
            log.exception("ArtMirror 启动失败: %s", exc)
            return None


def get_url() -> str | None:
    return f"http://127.0.0.1:{_state['port']}" if _state["port"] else None


def stop() -> None:
    with _state["lock"]:
        if _state["server"] is not None:
            _state["server"].should_exit = True
            _state["server"] = None
            _state["port"] = None
```

- [ ] **Step 4: 运行确认通过**

运行：`..\backend\.venv\Scripts\python.exe -m pytest comfyui-plugin\tests\test_artmirror_embed.py -q`
预期：2 passed（约需 1-3s 启动）。

- [ ] **Step 5: 提交**

```bash
git add comfyui-plugin/artmirror_embed.py comfyui-plugin/tests/test_artmirror_embed.py
git commit -m "feat: artmirror_embed 进程内 uvicorn 线程（临时端口/单例/可停）"
```

---

### Task 5: proxy 反向代理 + aiohttp 单测

**Files:**
- Create: `comfyui-plugin/proxy.py`
- Test: `comfyui-plugin/tests/test_proxy.py`

> 前置：测试环境需 `aiohttp`。执行：`..\backend\.venv\Scripts\python.exe -m pip install -q aiohttp`

- [ ] **Step 1: 写失败测试**

创建 `comfyui-plugin/tests/test_proxy.py`（纯 aiohttp，不依赖 pytest-asyncio/pytest-aiohttp）：

```python
"""/artmirror/* 反向代理核心逻辑测试（不经 ComfyUI，直接挂 aiohttp app）。"""
import asyncio
import json
import tempfile
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import artmirror_embed
import comfy_paths
import proxy


def _make_app() -> web.Application:
    app = web.Application()

    async def root(request):
        return web.HTTPFound("/artmirror/gallery.html")

    async def catch(request):
        return await proxy.handler(request)

    app.router.add_get("/artmirror", root)
    app.router.add_get("/artmirror/{tail:.*}", catch)
    app.router.add_post("/artmirror/{tail:.*}", catch)
    return app


def _check(path, method="GET", expect=200):
    """同步封装：启动 embed → 起代理 client → 请求断言 → 清理。"""
    async def run():
        with tempfile.TemporaryDirectory() as td:
            comfy_paths.set_paths(str(Path(td) / "user"), str(Path(td) / "out"))
            port = artmirror_embed.start()
            proxy.set_target(f"http://127.0.0.1:{port}")
            client = TestClient(TestServer(_make_app()))
            await client.start_server()
            try:
                r = await client.request(method, path, allow_redirects=False)
                body = await r.read()
                return r.status, r.headers, body
            finally:
                await client.close()
                artmirror_embed.stop()
    status, headers, body = asyncio.run(run())
    assert status == expect, f"status={status}"
    return status, headers, body


def test_proxy_health():
    _, _, body = _check("/artmirror/api/health")
    assert json.loads(body)["app"] == "artmirror"


def test_proxy_redirect():
    _, headers, _ = _check("/artmirror", expect=302)
    assert headers["Location"] == "/artmirror/gallery.html"


def test_proxy_static():
    _, _, body = _check("/artmirror/gallery.html")
    assert "画镜" in body.decode("utf-8", "ignore")
```

- [ ] **Step 2: 运行确认失败**

运行：`..\backend\.venv\Scripts\python.exe -m pytest comfyui-plugin\tests\test_proxy.py -q`
预期：FAIL（`ModuleNotFoundError: No module named 'proxy'`；若未装 aiohttp 则先装）。

- [ ] **Step 3: 创建 proxy.py**

创建 `comfyui-plugin/proxy.py`：

```python
"""/artmirror/* 反向代理：转发到进程内 ArtMirror（目标由 set_target 提供）。

测试/脱离 ComfyUI 时经 set_target 指向目标基址；ComfyUI 环境由 server.py 注入。
"""
import logging

import aiohttp
from aiohttp import web

log = logging.getLogger("artmirror.proxy")

_target = None  # 例如 http://127.0.0.1:54321


def set_target(base_url: str) -> None:
    global _target
    _target = base_url.rstrip("/")


def get_target() -> str | None:
    return _target


async def handler(request: web.Request) -> web.StreamResponse:
    target = get_target()
    if target is None:
        return web.Response(status=503, text="ArtMirror 后端未就绪")

    tail = request.match_info.get("tail", "")
    if not tail:
        return web.Response(status=302, headers={"Location": "/artmirror/gallery.html"})

    url = f"{target}/{tail}"
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length", "connection", "upgrade")
    }
    body = await request.read() if request.can_read_body else None

    async with aiohttp.ClientSession() as session:
        async with session.request(request.method, url, headers=headers, data=body) as resp:
            response = web.StreamResponse(
                status=resp.status,
                headers={"Content-Type": resp.content_type or "application/octet-stream"},
            )
            await response.prepare(request)
            async for chunk in resp.content.iter_chunked(64 * 1024):
                await response.write(chunk)
            await response.write_eof()
            return response
```

- [ ] **Step 4: 运行确认通过**

运行：`..\backend\.venv\Scripts\python.exe -m pytest comfyui-plugin\tests\test_proxy.py -q`
预期：3 passed。

- [ ] **Step 5: 提交**

```bash
git add comfyui-plugin/proxy.py comfyui-plugin/tests/test_proxy.py
git commit -m "feat: /artmirror/* 反向代理（流式转发，目标可注入）"
```

---

### Task 6: server.py 路由注册 + 默认扫描根集成

**Files:**
- Create: `comfyui-plugin/server.py`
- Modify: `comfyui-plugin/artmirror_embed.py`（追加 `ensure_default_scan_root()`）
- Test: `comfyui-plugin/tests/test_default_scan_root.py`

- [ ] **Step 1: 写失败测试**

创建 `comfyui-plugin/tests/test_default_scan_root.py`（先 `_configure` 再连库，避免用到默认 data_dir）：

```python
"""默认扫描根：空库时补 ComfyUI 输出目录。"""
import tempfile
from pathlib import Path

import artmirror_embed
import comfy_paths


def test_default_scan_root_added():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        user = td / "user"; out = td / "out"; out.mkdir()
        comfy_paths.set_paths(str(user), str(out))

        from artmirror_app.config import settings
        artmirror_embed._configure(settings)
        settings.ensure_dirs()

        from artmirror_app.database import get_session
        from artmirror_app.services import scanner
        with next(get_session()) as session:
            assert list(scanner.get_scan_roots(session)) == []

        artmirror_embed.ensure_default_scan_root()

        with next(get_session()) as session:
            roots = list(scanner.get_scan_roots(session))
            assert len(roots) == 1
            assert Path(roots[0]).resolve() == out.resolve()
```

- [ ] **Step 2: 运行确认失败**

运行：`..\backend\.venv\Scripts\python.exe -m pytest comfyui-plugin\tests\test_default_scan_root.py -q`
预期：FAIL（`AttributeError: ... no attribute 'ensure_default_scan_root'`）。

- [ ] **Step 3: 修改 artmirror_embed.py**

在 `artmirror_embed.py` 末尾追加（内部先配置运行目录再连库，保证独立可用）：

```python
def ensure_default_scan_root() -> None:
    """空库时将 ComfyUI 输出目录注册为扫描根（有根则不动）。"""
    try:
        from artmirror_app.config import settings
        _configure(settings)
        settings.ensure_dirs()
        from artmirror_app.database import get_session
        from artmirror_app.services import scanner
        with next(get_session()) as session:
            roots = list(scanner.get_scan_roots(session))
            if roots:
                return
            out = comfy_paths.get_output_dir()
            if out and Path(out).is_dir():
                scanner.save_scan_roots(session, [str(Path(out).resolve())])
    except Exception:  # noqa: BLE001
        log.exception("设置默认扫描根失败")
```

- [ ] **Step 4: 创建 server.py**

创建 `comfyui-plugin/server.py`：

```python
"""ComfyUI PromptServer 路由：/artmirror/* → 反向代理到进程内 ArtMirror。"""
import logging

from aiohttp import web

from . import artmirror_embed, proxy

log = logging.getLogger("artmirror.plugin")

try:
    from server import PromptServer
    _HAVE_COMFY = True
except Exception:  # noqa: BLE001
    PromptServer = None
    _HAVE_COMFY = False


async def _proxy(request: web.Request) -> web.StreamResponse:
    target = artmirror_embed.get_url()
    if target is None:
        port = artmirror_embed.start()
        if port is None:
            return web.Response(status=503, text="ArtMirror 启动失败，请查看 user/artmirror/server.log")
        target = f"http://127.0.0.1:{port}"
        proxy.set_target(target)
        artmirror_embed.ensure_default_scan_root()
    return await proxy.handler(request)


def register_proxy_routes() -> None:
    """在 ComfyUI PromptServer 上注册 /artmirror 路由（仅 ComfyUI 环境）。"""
    if not _HAVE_COMFY or PromptServer is None:
        return
    routes = PromptServer.instance.routes
    for method in ("get", "post", "delete"):
        routes.__getattribute__(method)("/artmirror")(_root)
        routes.__getattribute__(method)("/artmirror/{tail:.*}")(_proxy)


async def _root(request: web.Request) -> web.StreamResponse:
    return web.Response(status=302, headers={"Location": "/artmirror/gallery.html"})
```

- [ ] **Step 5: 运行确认通过**

运行：`..\backend\.venv\Scripts\python.exe -m pytest comfyui-plugin\tests\test_default_scan_root.py -q`
预期：1 passed。
回归：`..\backend\.venv\Scripts\python.exe -m pytest comfyui-plugin -q` 预期全绿（含前置任务用例）。

- [ ] **Step 6: 提交**

```bash
git add comfyui-plugin/server.py comfyui-plugin/artmirror_embed.py comfyui-plugin/tests/test_default_scan_root.py
git commit -m "feat: PromptServer 路由注册 + 默认扫描根（ComfyUI 输出目录）"
```

---

### Task 7: 前端同步 + 静态副本 + 前端扩展 tab

**Files:**
- Create: `comfyui-plugin/sync_frontend.py`
- Create: `comfyui-plugin/web/artmirror-tab.js`
- Create: `comfyui-plugin/static/`（由 sync_frontend.py 生成）

- [ ] **Step 1: 创建 sync_frontend.py**

创建 `comfyui-plugin/sync_frontend.py`：

```python
"""把 ArtMirror 主仓库 frontend/ 同步为插件内 static/。"""
import shutil
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent
REPO = PLUGIN.parent
SRC = REPO / "frontend"
DST = PLUGIN / "static"

_IGNORE = shutil.ignore_patterns("__pycache__")


def main() -> int:
    if not SRC.is_dir():
        print(f"未找到 {SRC}")
        return 1
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST, ignore=_IGNORE)
    print(f"已同步 {SRC} -> {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行同步**

运行：`..\backend\.venv\Scripts\python.exe comfyui-plugin\sync_frontend.py`
预期：输出「已同步 ... frontend -> ... static」；`static/gallery.html`、`static/api.js` 等存在。

- [ ] **Step 3: 创建 web/artmirror-tab.js**

创建 `comfyui-plugin/web/artmirror-tab.js`：

```js
import { app } from "../../scripts/app.js";

function mountArtMirror(el) {
  const iframe = document.createElement("iframe");
  iframe.src = "/artmirror/gallery.html";
  iframe.style.width = "100%";
  iframe.style.height = "100%";
  iframe.style.border = "0";
  iframe.setAttribute("allow", "clipboard-read; clipboard-write");
  el.appendChild(iframe);
}

app.registerExtension({
  name: "ArtMirror.Tab",
  async setup() {
    if (app.extensionManager?.registerSidebarTab) {
      app.extensionManager.registerSidebarTab({
        id: "artmirror-gallery",
        title: "图库",
        type: "custom",
        render: mountArtMirror,
      });
    } else if (app.extensionManager?.registerBottomPanelTab) {
      app.extensionManager.registerBottomPanelTab({
        id: "artmirror-gallery",
        title: "图库",
        type: "custom",
        render: mountArtMirror,
      });
    }
  },
});
```

- [ ] **Step 4: 静态校验**

- `Select-String -Path comfyui-plugin\web\artmirror-tab.js -Pattern "registerSidebarTab|iframe"` 命中
- `Test-Path comfyui-plugin/static/gallery.html`、`static/api.js`、`static/vendor/alpine.min.js` 均为 True
- 用 `node --check comfyui-plugin/web/artmirror-tab.js` 校验语法（若 node 可用）

- [ ] **Step 5: 提交**

```bash
git add comfyui-plugin/sync_frontend.py comfyui-plugin/web comfyui-plugin/static
git commit -m "feat: 前端同步脚本 + 静态副本 + 侧边栏图库 tab 扩展"
```

---

### Task 8: 端到端冒烟清单 + 文档收尾

**Files:**
- Modify: `comfyui-plugin/README.md`（补测试/开发/发布说明）

- [ ] **Step 1: 全量回归**

运行：`..\backend\.venv\Scripts\python.exe -m pytest comfyui-plugin -q`
预期：全部通过（Task 2-6 用例）。同时跑主仓库回归：`cd backend; uv run pytest -q`，预期全绿（插件改动不影响主仓库，`artmirror_app` 为副本）。

- [ ] **Step 2: 冒烟清单写入 README**

在 README 末尾追加：

```markdown
## 开发

- 同步后端：`python comfyui-plugin/sync_backend.py`（backend/app → artmirror_app/）
- 同步前端：`python comfyui-plugin/sync_frontend.py`（frontend/ → static/）
- 测试：`..\backend\.venv\Scripts\python.exe -m pip install aiohttp` 后
  `..\backend\.venv\Scripts\python.exe -m pytest comfyui-plugin -q`

## 手工冒烟（Windows）

1. 把 `comfyui-plugin` 目录拷入 ComfyUI `custom_nodes/`（或 `git clone` 到独立仓库）
2. 重启 ComfyUI（Desktop 或网页版），侧边栏出现「图库」tab
3. 点开 tab → 自动启动后端并扫描输出目录；确认图库可浏览、meta 解析、设置可保存
4. 若 503/白屏：查看 ComfyUI 日志与 `user/artmirror/server.log`

## 发布 Registry（可选）

1. 用 `git subtree split` 把 `comfyui-plugin/` 拆为独立仓库 `ComfyUI-ArtMirror`
2. 填 `pyproject.toml` 的 `[tool.comfy] PublisherId`
3. `comfy node publish --install-deps`（或配置 GitHub Actions）
4. 发布 stable 后，Desktop「Manage Extensions」搜索安装验证
```

- [ ] **Step 3: 提交**

```bash
git add comfyui-plugin/README.md
git commit -m "docs: 插件测试/冒烟/发布说明"
```

---

## Self-Review

* **Spec 覆盖**：架构总览（Task 4-6）、仓库结构（Task 1-2、7）、嵌入 tab（Task 7）、反向代理（Task 5）、数据目录 user/artmirror（Task 3-4、6）、默认扫描根输出目录（Task 6）、依赖与 Registry（Task 1、8）、后端同步零改动（Task 2）、错误处理（503/日志，Task 5-6）、测试与冒烟（Task 3-8）——全覆盖。
* **占位符**：无 TBD/TODO；`[tool.comfy] PublisherId` 为发布时用户填写值，已注明。
* **类型一致性**：`proxy.set_target`/`get_target`（Task 5 定义，Task 6 server.py 使用一致）；`artmirror_embed.start()/stop()/get_url()/ensure_default_scan_root()`（Task 4/6 定义与使用一致）；`comfy_paths.set_paths/get_user_dir/get_output_dir`（Task 3 定义，Task 4/6 使用一致）；`server.register_proxy_routes` 被 `__init__._register_routes` 调用（Task 1/6 一致）。
* **风险提示**：`aiohttp` 需装入测试 venv（Task 5 前置已写）；`server.py` 对 `PromptServer.instance.routes` 的装饰器用法与社区 SDFX 先例一致，若 ComfyUI 版本路由 API 有差异由 Task 8 冒烟兜底。
