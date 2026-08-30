"""在 ComfyUI 进程内以后台线程运行 ArtMirror FastAPI（临时端口）。"""
import logging
import threading
import time
from pathlib import Path

import uvicorn

try:
    from . import comfy_paths
except ImportError:  # 顶层导入（pytest）时回退绝对导入
    import comfy_paths

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
