"""后台常驻线程：定期对注册根目录做增量扫描，有变动则递增同步版本号。

前端轮询 ``/api/sync/version``，版本变化即重新拉取图库，实现本地图片增删的实时同步。
"""
from __future__ import annotations

import threading

from sqlmodel import Session

from ..database import engine
from . import scanner

SYNC_INTERVAL = 20.0  # 秒：降低频率，避免常驻占用与阻塞用户操作
_version = 0
_ver_lock = threading.Lock()
_stop_event = threading.Event()
_thread: threading.Thread | None = None
_scanning = threading.Lock()  # 跳过重叠扫描，避免无限堆积


def get_version() -> int:
    """读取当前同步版本号。"""
    with _ver_lock:
        return _version


def bump() -> None:
    """手动递增版本号（注册/移除根目录后立即触发前端刷新）。"""
    _bump()


def _bump() -> None:
    global _version
    with _ver_lock:
        _version += 1


def _loop() -> None:
    """循环扫描；任何新增/更新/移除都会递增版本号。"""
    while not _stop_event.is_set():
        if _scanning.acquire(blocking=False):  # 上一次扫描未结束则跳过本轮
            try:
                with Session(engine) as session:
                    roots = scanner.get_scan_roots(session)
                    if roots:
                        stats = scanner.scan_all(session, roots)
                        if stats.new or stats.updated or stats.removed:
                            _bump()
            except Exception:  # noqa: BLE001
                pass
            finally:
                _scanning.release()
        _stop_event.wait(SYNC_INTERVAL)


def start() -> None:
    """启动后台同步线程（幂等）。"""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="am-sync")
    _thread.start()


def stop() -> None:
    """停止后台同步线程。"""
    global _thread
    _stop_event.set()
    if _thread:
        _thread.join(timeout=2)
    _thread = None