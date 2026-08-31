"""在 ComfyUI 进程内以后台线程运行 ArtMirror FastAPI（临时端口）。

插件端启动器：仓库根即插件，直接复用根目录 artmirror/ 核心包与 frontend/ 前端，
无任何代码副本。
"""
import logging
import threading
import time
from pathlib import Path

import uvicorn

import comfy_paths
from artmirror.config import settings
from artmirror.database import get_engine, reset_engine
from artmirror.main import create_app

log = logging.getLogger("artmirror.embed")

_state = {"lock": threading.Lock(), "server": None, "port": None}


def resolve_data_dir() -> str:
    return str(Path(comfy_paths.get_user_dir()) / "artmirror")


def resolve_frontend_dir() -> str:
    """仓库根即插件：前端即根目录 frontend/（web 端与插件端共用同一份）。"""
    return str(Path(__file__).resolve().parent / "frontend")


def _prepare() -> None:
    """按插件环境覆盖配置并重建 engine 绑定。"""
    settings.configure(data_dir=resolve_data_dir(), frontend_dir=resolve_frontend_dir())
    settings.ensure_dirs()
    reset_engine()


def start() -> int | None:
    """启动 ArtMirror（单例）。成功返回端口，失败返回 None。"""
    with _state["lock"]:
        if _state["port"] is not None:
            return _state["port"]
        try:
            _prepare()
            app = create_app()
            server = uvicorn.Server(
                uvicorn.Config(app, host="127.0.0.1", port=0,
                               log_config=None, access_log=False)
            )
            thread = threading.Thread(target=server.run, daemon=True, name="artmirror")
            thread.start()

            port = None
            for _ in range(100):
                servers = getattr(server, "servers", None)
                if servers and servers[0].sockets:
                    port = servers[0].sockets[0].getsockname()[1]
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
    # 释放 SQLite 句柄：不 dispose 时引擎连接池持有 artmirror.db，
    # Windows 上会导致文件被占用，无法删除/覆盖。
    try:
        get_engine().dispose()
    except Exception:  # noqa: BLE001
        pass


def ensure_default_scan_root() -> None:
    """空库时将 ComfyUI 输出目录注册为扫描根（有根则不动）。"""
    try:
        _prepare()
        from artmirror.database import get_session
        from artmirror.services import scanner
        with next(get_session()) as session:
            roots = list(scanner.get_scan_roots(session))
            if roots:
                return
            out = comfy_paths.get_output_dir()
            if out and Path(out).is_dir():
                scanner.save_scan_roots(session, [str(Path(out).resolve())])
    except Exception:  # noqa: BLE001
        log.exception("设置默认扫描根失败")
