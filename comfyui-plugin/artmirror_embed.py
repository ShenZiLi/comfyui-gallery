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
    Path(settings.frontend_dir).mkdir(parents=True, exist_ok=True)


def _rebind_engine(settings) -> None:
    """将 artmirror_app.database.engine 重建绑定到当前 db_path。

    database.py 的 engine 在模块首次导入时即按当时的 data_dir 绑定；进程内
    stop 后再次 start()（或更换用户目录）时模块已缓存、不会重跑，需重建绑定，
    否则引擎仍指向旧库，data_dir 覆盖不生效。
    """
    from sqlmodel import create_engine

    from artmirror_app import database as db

    db.engine = create_engine(
        f"sqlite:///{settings.db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )


def start() -> int | None:
    """启动 ArtMirror（单例）。成功返回端口，失败返回 None。"""
    with _state["lock"]:
        if _state["port"] is not None:
            return _state["port"]
        try:
            # 先配置 settings（覆盖 data_dir/frontend_dir），再导入 app_main——
            # artmirror_app.database 的 engine 与 main 的 StaticFiles 挂载均在导入期绑定，
            # 必须先配置后导入，否则覆盖不生效（DB 落在默认 data/、前端指向默认 frontend/）。
            from artmirror_app.config import settings

            _configure(settings)
            settings.ensure_dirs()

            # 重建引擎绑定：确保 database.engine 指向当前 db_path（首次导入或复用）。
            _rebind_engine(settings)

            from artmirror_app import main as app_main

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
    # 释放 SQLite 句柄：不 dispose 时引擎连接池持有 artmirror.db，
    # Windows 上会导致文件被占用，无法删除/覆盖。
    try:
        from artmirror_app.database import engine as db_engine
        db_engine.dispose()
    except Exception:  # noqa: BLE001
        pass


def ensure_default_scan_root() -> None:
    """空库时将 ComfyUI 输出目录注册为扫描根（有根则不动）。"""
    try:
        from artmirror_app.config import settings
        _configure(settings)
        _rebind_engine(settings)
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
