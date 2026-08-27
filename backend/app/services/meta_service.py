"""图片 meta 入库服务。

把 ComfyUI 解析结果落库并维护标签（模型/LoRA/VAE）多对多关系。
"""
from __future__ import annotations

from ..models import ImageAsset, ImageTag, Tag, WorkflowMeta
from ..parsers.comfyui_parser import ParseResult
from sqlmodel import Session, select


def tag_category(asset_kind: str) -> str:
    """统一标签类别命名。"""
    return {"model": "model", "lora": "lora", "vae": "vae"}.get(asset_kind, "special")


def get_or_create_tag(session: Session, name: str, category: str) -> Tag:
    """按 (name, category) 获取或新建标签，维护使用计数。"""
    tag = session.exec(
        select(Tag).where(Tag.name == name, Tag.category == category)
    ).first()
    if tag is None:
        tag = Tag(name=name, category=category, count=1)
        session.add(tag)
        session.flush()
    else:
        tag.count += 1
    return tag


def ingest(session: Session, image: ImageAsset, result: ParseResult) -> None:
    """为图片写入（或更新）workflow_meta 与标签。"""
    meta = session.exec(
        select(WorkflowMeta).where(WorkflowMeta.image_id == image.id)
    ).first()
    if meta is None:
        meta = WorkflowMeta(image_id=image.id)
        session.add(meta)
    meta.prompt = result.prompt
    meta.negative_prompt = result.negative_prompt
    meta.prompt_graph_json = _dumps(result.prompt_graph)
    meta.workflow_json = _dumps(result.workflow)
    meta.steps = result.steps
    meta.cfg = result.cfg
    meta.sampler = result.sampler
    meta.scheduler = result.scheduler
    meta.seed = result.seed
    meta.denoise = result.denoise
    meta.model_name = result.model_name

    image.prompt_type = "origin" if result.prompt else "none"

    # 标签
    if result.model_name:
        _link(session, image.id, result.model_name, "model")
    for lora in result.loras:
        _link(session, image.id, lora, "lora")
    if result.vae:
        _link(session, image.id, result.vae, "vae")


def _link(session: Session, image_id: int, name: str, category: str) -> None:
    tag = get_or_create_tag(session, name, category)
    exists = session.exec(
        select(ImageTag).where(ImageTag.image_id == image_id, ImageTag.tag_id == tag.id)
    ).first()
    if exists is None:
        session.add(ImageTag(image_id=image_id, tag_id=tag.id))


def _dumps(obj) -> str:
    if obj is None:
        return ""
    import json

    return json.dumps(obj, ensure_ascii=False, indent=2)