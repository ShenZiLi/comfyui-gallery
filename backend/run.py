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
