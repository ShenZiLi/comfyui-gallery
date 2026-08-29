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
        force=True,  # root 已有 handler（如 pytest 捕获）时仍重建落盘，保证文件必然创建
    )
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
