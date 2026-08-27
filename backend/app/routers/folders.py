"""目录路由。"""
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..database import get_session
from ..models import ImageAsset, Folder

router = APIRouter(prefix="/api/folders", tags=["folders"])


@router.get("")
def list_folders(session: Session = Depends(get_session)):
    """返回目录树（含各自图片数量）。"""
    folders = session.exec(
        select(Folder).where(Folder.is_deleted == 0).order_by(Folder.path)
    ).all()
    counts = {}
    for row in session.exec(select(ImageAsset).where(ImageAsset.is_deleted == 0)).all():
        counts[row.folder_id] = counts.get(row.folder_id, 0) + 1
    return [
        {
            "id": f.id,
            "parentId": f.parent_id,
            "name": f.name,
            "path": f.path,
            "count": counts.get(f.id, 0),
        }
        for f in folders
    ]