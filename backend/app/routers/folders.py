"""目录路由。"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..database import get_session
from ..models import ImageAsset, Folder, Setting
from ..services import watcher

router = APIRouter(prefix="/api/folders", tags=["folders"])


def _get_hidden(session: Session) -> set[int]:
    """读取被隐藏的文件夹 id 集合。"""
    row = session.exec(select(Setting).where(Setting.key == "hidden_folders")).first()
    try:
        data = json.loads(row.value) if row and row.value else []
        return {int(x) for x in data}
    except Exception:  # noqa: BLE001
        return set()


def _set_hidden(session: Session, ids: set[int]) -> None:
    data = json.dumps(sorted(int(x) for x in ids))
    row = session.exec(select(Setting).where(Setting.key == "hidden_folders")).first()
    if row is None:
        session.add(Setting(key="hidden_folders", value=data))
    else:
        row.value = data
    session.commit()


@router.get("")
def list_folders(session: Session = Depends(get_session)):
    """返回已注册图片目录下扫描到的文件夹（含图片数量与隐藏状态）。

    强调关联：仅返回落在当前注册根目录前缀下的文件夹；根目录增删导致该集合变化。
    """
    from ..services import scanner

    roots = scanner.get_scan_roots(session)
    root_prefixes = [str(r).rstrip("/") for r in roots]

    def _under_root(path: str) -> bool:
        # 精确匹配根目录自身，或严格落在某个根目录「之下」的路径
        return any(
            path == rp or path.startswith(rp + "/") for rp in root_prefixes if rp
        )

    folders = session.exec(
        select(Folder).where(Folder.is_deleted == 0, Folder.path.startswith("/")).order_by(Folder.path)
    ).all()
    folders = [f for f in folders if _under_root(f.path)]

    counts = {}
    for row in session.exec(select(ImageAsset).where(ImageAsset.is_deleted == 0)).all():
        counts[row.folder_id] = counts.get(row.folder_id, 0) + 1
    hidden = _get_hidden(session)
    return [
        {
            "id": f.id,
            "parentId": f.parent_id,
            "name": f.name,
            "path": f.path,
            "count": counts.get(f.id, 0),
            "hidden": f.id in hidden,
        }
        for f in folders
    ]


@router.post("/{folder_id}/toggle-hidden")
def toggle_hidden(folder_id: int, session: Session = Depends(get_session)):
    """切换文件夹隐藏状态：置灰隐藏后图库不再展示其图片，再次点击恢复。"""
    folder = session.get(Folder, folder_id)
    if folder is None or folder.is_deleted:
        raise HTTPException(404, "folder not found")
    hidden = _get_hidden(session)
    if folder_id in hidden:
        hidden.discard(folder_id)
    else:
        hidden.add(folder_id)
    _set_hidden(session, hidden)
    watcher.bump()  # 让图库页轮询刷新
    return {"folderId": folder_id, "hidden": folder_id in hidden, "hiddenIds": sorted(hidden)}