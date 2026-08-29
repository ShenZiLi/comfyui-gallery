"""run.py 打包入口辅助函数测试（app/run_helpers.py）。"""
import logging
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
    """日志落盘到指定文件，且内容实际写入。"""
    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "server.log"
        setup_file_logging(log_path)
        assert log_path.exists()
        old = logging.getLogger().handlers[:]  # 保存现场，便于恢复
        try:
            logging.getLogger("test").info("hello-artmirror-log")
        finally:
            # Windows 上 FileHandler 会锁定文件，关闭并移除 handler 释放句柄，
            # 避免影响后续用例日志捕获
            for h in list(logging.getLogger().handlers):
                logging.getLogger().removeHandler(h)
                h.close()
        assert "hello-artmirror-log" in open(log_path, encoding="utf-8").read()
