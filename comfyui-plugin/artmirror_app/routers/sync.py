"""同步版本号路由。

前端轮询该版本号，变化即重新拉取图库，实现本地图片增删的实时同步。
"""
from fastapi import APIRouter

from ..services import watcher

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/version")
def sync_version() -> dict:
    """返回当前同步版本号。"""
    return {"version": watcher.get_version()}