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


def _basename(name: str) -> str:
    """只保留名称：剥离反斜杠或正斜杠分隔的路径前缀。"""
    return name.replace("\\", "/").rsplit("/", 1)[-1].strip()


def migrate_tag_paths(session: Session) -> None:
    """一次性迁移：把历史 Tag 名称归一为 basename，合并重复，保持筛选一致。"""
    rows = session.exec(select(Tag).where(Tag.is_deleted == 0)).all()
    for tag in rows:
        base = _basename(tag.name)
        if base == tag.name or not base:
            continue
        target = session.exec(
            select(Tag).where(
                Tag.name == base, Tag.category == tag.category, Tag.is_deleted == 0
            )
        ).first()
        if target is None:
            # 无同名标签，直接改名
            tag.name = base
            continue
        if target.id == tag.id:
            continue
        # 合并：ImageTag 改指 target，计数合并，旧标签软删
        links = session.exec(
            select(ImageTag).where(ImageTag.tag_id == tag.id)
        ).all()
        count = 0
        for link in links:
            exists = session.exec(
                select(ImageTag).where(
                    ImageTag.image_id == link.image_id, ImageTag.tag_id == target.id
                )
            ).first()
            if exists is None:
                link.tag_id = target.id
                count += 1
            else:
                session.delete(link)
        target.count += count
        tag.is_deleted = 1
        tag.count = 0
    session.commit()


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
    meta.origin_prompts_json = _dumps_list(result.positive_prompts)
    meta.negative_prompts_json = _dumps_list(result.negative_prompts)
    meta.prompt_graph_json = _dumps(result.prompt_graph)
    meta.workflow_json = _dumps(result.workflow)
    meta.steps = result.steps
    meta.cfg = result.cfg
    meta.sampler = result.sampler
    meta.scheduler = result.scheduler
    meta.seed = result.seed
    meta.denoise = result.denoise
    meta.model_name = _basename(result.model_name)

    image.prompt_type = "origin" if result.prompt else "none"

    # 标签（仅存模型名，剥离路径前缀）
    if result.model_name:
        _link(session, image.id, _basename(result.model_name), "model")
    for lora in result.loras:
        _link(session, image.id, _basename(lora), "lora")
    if result.vae:
        _link(session, image.id, _basename(result.vae), "vae")


def _link(session: Session, image_id: int, name: str, category: str) -> None:
    # 只保留文件/模型名：剥离 checkpoints/、LoRA/ 等路径前缀（兼容 \ 与 /）
    name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name:
        return
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


def _dumps_list(items) -> str:
    if not items:
        return ""
    import json

    cleaned = [str(x).strip() for x in items if str(x or "").strip()]
    if not cleaned:
        return ""
    return json.dumps(cleaned, ensure_ascii=False)


def replace_asset_tags(
    session: Session, image_id: int, assets: dict[str, list[str]]
) -> None:
    """按资源类别重建该图标签（如 AI 重解析结果）。

    assets 形如 {"model": ["..."], "lora": ["..."], "vae": ["..."]}。
    先解除并清理这些类别旧的关联，再按新名单重建；未在 assets 中的类别保留。
    需调用方 commit。
    """
    cats = set(assets)
    # 1) 解除该图在目标类别上的旧关联并回收计数
    for link in session.exec(
        select(ImageTag).where(ImageTag.image_id == image_id)
    ).all():
        tag = session.get(Tag, link.tag_id)
        if tag is None or tag.category not in cats:
            continue
        session.delete(link)
        tag.count = max(0, (tag.count or 0) - 1)
    # 2) 按新名单重建（basename 去重）
    for cat, names in assets.items():
        seen = set()
        for name in names:
            base = _basename(name)
            if base and base not in seen:
                seen.add(base)
                _link(session, image_id, base, cat)