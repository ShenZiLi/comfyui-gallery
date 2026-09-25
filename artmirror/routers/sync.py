"""同步版本号路由。

前端轮询版本号，并根据刷新版本区分后台新增图片与自动刷新操作。
"""
from fastapi import APIRouter

from ..services import watcher

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/version")
def sync_version() -> dict:
    """返回同步版本号及自动刷新版本号。"""
    return watcher.get_sync_state()
