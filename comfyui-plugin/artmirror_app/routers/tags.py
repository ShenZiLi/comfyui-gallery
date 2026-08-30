"""标签路由。"""
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..database import get_session
from ..models import Tag

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("")
def list_tags(session: Session = Depends(get_session)):
    """返回全部标签（用于筛选 chips）。"""
    rows = session.exec(
        select(Tag).where(Tag.is_deleted == 0).order_by(Tag.category, Tag.name)
    ).all()
    return [{"name": t.name, "category": t.category} for t in rows]