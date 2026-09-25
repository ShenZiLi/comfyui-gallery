"""同步版本区分后台新增图片与需要自动刷新的操作。"""

from artmirror.routers.sync import sync_version
from artmirror.services import watcher


def test_sync_version_distinguishes_background_additions(monkeypatch):
    monkeypatch.setattr(watcher, "_version", 0)
    monkeypatch.setattr(watcher, "_auto_version", 0)

    assert sync_version() == {"version": 0, "auto_version": 0}

    watcher._bump()  # 定时扫描新增图片
    assert sync_version() == {"version": 1, "auto_version": 0}

    watcher.bump()  # 手动导入、设置操作或仅更新/移除图片
    assert sync_version() == {"version": 2, "auto_version": 1}
