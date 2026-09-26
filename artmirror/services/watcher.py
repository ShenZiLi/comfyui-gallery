"""后台常驻线程：定期对注册根目录做增量扫描，有变动则递增同步版本号。

前端轮询 ``/api/sync/version``：新增图片提示手动刷新，其余变化自动刷新。
"""
from __future__ import annotations

import threading

from sqlmodel import Session

from ..database import get_engine
from . import scanner, scan_tasks

SYNC_INTERVAL = 20.0  # 秒：降低频率，避免常驻占用与阻塞用户操作
_version = 0
_auto_version = 0
_ver_lock = threading.Lock()
_stop_event = threading.Event()
_thread: threading.Thread | None = None


def get_version() -> int:
    """读取当前同步版本号。"""
    with _ver_lock:
        return _version


def get_sync_state() -> dict[str, int]:
    """返回总版本与自动刷新版本，供图库区分后台新增图片。"""
    with _ver_lock:
        return {"version": _version, "auto_version": _auto_version}


def bump() -> None:
    """主动操作或非新增扫描变更：递增版本并触发自动刷新。"""
    global _version, _auto_version
    with _ver_lock:
        _version += 1
        _auto_version += 1


def _bump() -> None:
    """定时扫描新增图片：只递增总版本，等待图库用户点击。"""
    global _version
    with _ver_lock:
        _version += 1


def _loop() -> None:
    """循环扫描；新增图片提示，只有更新/移除则自动刷新。"""
    while not _stop_event.is_set():
        try:
            with Session(get_engine()) as session:
                roots = scanner.get_scan_roots(session)
            if roots:
                # 协调器忙碌时 watcher 请求被丢弃，本轮不会与其他扫描重叠。
                scan_tasks.request_scan(roots, source="watcher", reparse_missing=False)
        except Exception:  # noqa: BLE001
            pass
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
