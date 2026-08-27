"""图片查询与文件服务路由。"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..config import settings
from ..database import get_session
from ..models import (
    ImageAsset,
    ImageTag,
    PromptTranslation,
    ReversePrompt,
    Tag,
    WorkflowMeta,
)

router = APIRouter(prefix="/api/images", tags=["images"])


def _tags_of(session: Session, image_id: int) -> list[dict]:
    rows = session.exec(
        select(Tag).join(ImageTag, ImageTag.tag_id == Tag.id).where(
            ImageTag.image_id == image_id, ImageTag.is_deleted == 0
        )
    ).all()
    return [{"name": t.name, "category": t.category} for t in rows]


def _latest(session: Session, model, image_id: int) -> dict | None:
    row = session.exec(
        select(model).where(model.image_id == image_id).order_by(model.id.desc())
    ).first()
    return row


def to_card(session: Session, im: ImageAsset) -> dict:
    """组装图库卡片数据。"""
    meta = session.exec(
        select(WorkflowMeta).where(WorkflowMeta.image_id == im.id)
    ).first()
    reverse = _latest(session, ReversePrompt, im.id)
    trans = session.exec(
        select(PromptTranslation).where(
            PromptTranslation.image_id == im.id,
            PromptTranslation.prompt_kind == "origin",
            PromptTranslation.lang == "zh",
        )
    ).first()
    params = {
        "steps": meta.steps if meta else None,
        "cfg": meta.cfg if meta else None,
        "sampler": meta.sampler if meta else None,
        "scheduler": meta.scheduler if meta else None,
        "seed": meta.seed if meta else None,
        "denoise": meta.denoise if meta else None,
    }
    return {
        "id": im.id,
        "folderId": im.folder_id,
        "name": im.file_name,
        "width": im.width,
        "height": im.height,
        "rating": im.rating,
        "aiRating": im.ai_rating,
        "prompt": meta.prompt if meta else "",
        "negative": meta.negative_prompt if meta else "",
        "reversePrompt": reverse.text if reverse else None,
        "translationZH": trans.text if trans else None,
        "tags": _tags_of(session, im.id),
        "params": params,
        "thumb": f"/api/images/{im.id}/thumb",
    }


def to_detail(session: Session, im: ImageAsset) -> dict:
    card = to_card(session, im)
    meta = session.exec(
        select(WorkflowMeta).where(WorkflowMeta.image_id == im.id)
    ).first()
    card["model"] = meta.model_name if meta else ""
    card["promptGraph"] = meta.prompt_graph_json if meta else ""
    card["workflow"] = meta.workflow_json if meta else ""
    card["path"] = im.file_path
    return card


def _query_images(session: Session, folder_id, tag, q, sort):
    stmt = select(ImageAsset).where(ImageAsset.is_deleted == 0)
    if folder_id:
        stmt = stmt.where(ImageAsset.folder_id == folder_id)
    if tag:
        stmt = stmt.join(
            ImageTag, ImageTag.image_id == ImageAsset.id
        ).join(Tag, Tag.id == ImageTag.tag_id).where(Tag.name == tag)
    if q:
        like = f"%{q}%"
        stmt = stmt.join(
            WorkflowMeta, WorkflowMeta.image_id == ImageAsset.id, isouter=True
        ).where(
            (WorkflowMeta.prompt.like(like))
            | (WorkflowMeta.negative_prompt.like(like))
            | (ImageAsset.file_name.like(like))
        ).distinct()
    order = ImageAsset.ai_rating.desc().nullslast()
    if sort == "manual":
        order = ImageAsset.rating.desc().nullslast()
    if sort == "time":
        order = ImageAsset.id.desc()
    return session.exec(stmt.order_by(order)).all()


@router.get("")
def list_images(
    folderId: int | None = None,
    tag: str | None = None,
    q: str | None = None,
    sort: str = "ai",
    session: Session = Depends(get_session),
):
    """列出图片卡片（过滤器 + 排序）。"""
    imgs = _query_images(session, folderId, tag, q, sort)
    return [to_card(session, im) for im in imgs]


@router.get("/{image_id}")
def get_image(image_id: int, session: Session = Depends(get_session)):
    im = session.get(ImageAsset, image_id)
    if im is None or im.is_deleted:
        raise HTTPException(404, "image not found")
    return to_detail(session, im)


@router.get("/{image_id}/thumb")
def thumb(image_id: int, session: Session = Depends(get_session)):
    im = session.get(ImageAsset, image_id)
    if im is None or im.is_deleted:
        raise HTTPException(404)
    path = settings.thumbs_dir / f"{im.sha256}.webp"
    if path.exists():
        return FileResponse(path)
    raise HTTPException(404, "thumbnail not ready")


@router.get("/{image_id}/file")
def file(image_id: int, session: Session = Depends(get_session)):
    """返回原始图片文件（供预览/下载）。"""
    im = session.get(ImageAsset, image_id)
    if im is None or im.is_deleted:
        raise HTTPException(404)
    return FileResponse(im.abs_path, filename=im.file_name)