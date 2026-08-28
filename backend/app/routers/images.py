"""图片查询与文件服务路由。"""
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..config import settings
from ..database import get_session
from ..models import (
    ImageAsset,
    ImageTag,
    PromptTranslation,
    RatingRecord,
    ReversePrompt,
    Tag,
    WorkflowMeta,
)
from ..services import meta_service, llm, watcher

router = APIRouter(prefix="/api/images", tags=["images"])


def _basename(name: str) -> str:
    """只保留名称：剥离 \\ 或 / 分隔的路径前缀。"""
    return name.replace("\\", "/").rsplit("/", 1)[-1].strip()


def _load_str_list(text: str) -> list[str]:
    if not text:
        return []
    try:
        import json

        data = json.loads(text)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x or "").strip()]
    except Exception:  # noqa: BLE001
        pass
    return []


def _tags_of(session: Session, image_id: int) -> list[dict]:
    rows = session.exec(
        select(Tag).join(ImageTag, ImageTag.tag_id == Tag.id).where(
            ImageTag.image_id == image_id, ImageTag.is_deleted == 0
        )
    ).all()
    return [{"name": _basename(t.name), "category": t.category} for t in rows]


def _latest(session: Session, model, image_id: int) -> dict | None:
    row = session.exec(
        select(model).where(model.image_id == image_id).order_by(model.id.desc())
    ).first()
    return row


def _latest_ai_reason(session: Session, image_id: int) -> str:
    rec = session.exec(
        select(RatingRecord)
        .where(RatingRecord.image_id == image_id, RatingRecord.rating_type == "ai")
        .order_by(RatingRecord.id.desc())
    ).first()
    return rec.reason if rec else ""


def _hidden_folders(session: Session) -> set[int]:
    from ..models import Setting

    row = session.exec(select(Setting).where(Setting.key == "hidden_folders")).first()
    try:
        import json

        data = json.loads(row.value) if row and row.value else []
        return {int(x) for x in data}
    except Exception:  # noqa: BLE001
        return set()


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
    ai_record = _latest_ai_reason(session, im.id)
    return {
        "id": im.id,
        "folderId": im.folder_id,
        "name": im.file_name,
        "width": im.width,
        "height": im.height,
        "fileSize": im.file_size,
        "rating": im.rating,
        "aiRating": im.ai_rating,
        "aiReason": ai_record,
        "prompt": meta.prompt if meta else "",
        "negative": meta.negative_prompt if meta else "",
        "originPrompts": _load_str_list(meta.origin_prompts_json if meta else "") or ([meta.prompt] if meta and meta.prompt else []),
        "negativePrompts": _load_str_list(meta.negative_prompts_json if meta else ""),
        "aiPrompts": _load_str_list(meta.ai_prompts_json if meta else "") or ([meta.ai_prompt] if meta and meta.ai_prompt else []),
        "aiPrompt": meta.ai_prompt if meta else "",
        "aiNegative": meta.ai_negative_prompt if meta else "",
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
    card["model"] = _basename(meta.model_name) if meta and meta.model_name else ""
    card["promptGraph"] = meta.prompt_graph_json if meta else ""
    card["workflow"] = meta.workflow_json if meta else ""
    card["path"] = im.file_path
    # 各提示词源已持久化的中英译文：{kind: {lang: text}}
    translations: dict[str, dict[str, str]] = {}
    for t in session.exec(
        select(PromptTranslation).where(PromptTranslation.image_id == im.id)
    ).all():
        translations.setdefault(t.prompt_kind, {})[t.lang] = t.text
    card["translations"] = translations
    return card


def _kind_prompt(session: Session, im: ImageAsset, kind: str) -> str:
    """取某个提示词源的主文本（用于互译）。"""
    if kind == "reverse":
        rev = _latest(session, ReversePrompt, im.id)
        return rev.text if rev else ""
    meta = session.exec(
        select(WorkflowMeta).where(WorkflowMeta.image_id == im.id)
    ).first()
    if kind == "ai":
        items = _load_str_list(meta.ai_prompts_json if meta else "") or (
            [meta.ai_prompt] if meta and meta.ai_prompt else []
        )
    else:  # origin
        items = _load_str_list(meta.origin_prompts_json if meta else "") or (
            [meta.prompt] if meta and meta.prompt else []
        )
    return "\n".join(items).strip()


def _detect_target_lang(text: str) -> str:
    """含中文则互译为英文，否则译为中文。"""
    return "en" if re.search(r"[\u4e00-\u9fff]", text) else "zh"


@router.post("/{image_id}/translate")
def translate_prompt_image(image_id: int, body: dict, session: Session = Depends(get_session)):
    """对某提示词源做中英互译并持久化；已有译文直接返回而不请求 AI。"""
    im = session.get(ImageAsset, image_id)
    if im is None or im.is_deleted:
        raise HTTPException(404, "image not found")
    kind = str((body.get("kind") or "origin")).strip()
    if kind not in ("origin", "reverse", "ai"):
        raise HTTPException(400, "kind 仅支持 origin / reverse / ai")
    src = _kind_prompt(session, im, kind)
    if not src:
        raise HTTPException(400, "该提示词源暂无内容，无法翻译")

    target = _detect_target_lang(src)
    exists = session.exec(
        select(PromptTranslation).where(
            PromptTranslation.image_id == im.id,
            PromptTranslation.prompt_kind == kind,
            PromptTranslation.lang == target,
        )
    ).first()
    if exists is not None:
        return {"text": exists.text, "lang": target, "cached": True}

    try:
        translated = llm.translate_prompt(src, target, session)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    row = PromptTranslation(image_id=im.id, prompt_kind=kind, lang=target, text=translated)
    session.add(row)
    session.commit()
    return {"text": translated, "lang": target, "cached": False}


def _query_images(session: Session, folder_id, tag, q, sort):
    stmt = select(ImageAsset).where(ImageAsset.is_deleted == 0)
    hidden = _hidden_folders(session)
    if hidden:
        stmt = stmt.where(
            ImageAsset.folder_id.is_(None)
            | (~ImageAsset.folder_id.in_(list(hidden)))
        )
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


@router.delete("/{image_id}")
def delete_image(image_id: int, session: Session = Depends(get_session)):
    """删除一张图片：物理文件移入系统废纸篓，并软删其入库记录。"""
    im = session.get(ImageAsset, image_id)
    if im is None or im.is_deleted:
        raise HTTPException(404, "image not found")

    path = Path(im.abs_path)
    if path.exists():
        _move_to_trash(path)  # 失败会抛出，从而中断删除

    # 软删入库记录并回收标签计数
    im.is_deleted = 1
    for link in session.exec(
        select(ImageTag).where(ImageTag.image_id == image_id)
    ).all():
        tag = session.get(Tag, link.tag_id)
        session.delete(link)
        if tag is not None:
            tag.count = max(0, (tag.count or 0) - 1)
    session.commit()
    watcher.bump()
    return {"ok": True, "id": image_id, "moved_to_trash": True}


def _move_to_trash(path: Path) -> None:
    """把文件移入系统废纸篓。

    优先 send2trash（处理交叉卷/权限正确性）；若因 macOS Automation 权限等失败，
    回退为直接把文件移入用户主目录废纸篓 ~/.Trash，避免删除被中断。
    """
    try:
        import send2trash
        send2trash.send2trash(str(path))
        return
    except Exception:  # noqa: BLE001
        pass

    import shutil

    trash_dir = Path.home() / ".Trash"
    trash_dir.mkdir(exist_ok=True)
    target = trash_dir / path.name
    # 处理同名冲突：macOS 惯例追加序号
    if target.exists():
        stem, suffix = path.stem, path.suffix
        i = 1
        while target.exists():
            target = trash_dir / f"{stem} - {i}{suffix}"
            i += 1
    try:
        shutil.move(str(path), str(target))
    except OSError as exc:
        raise HTTPException(500, f"移入废纸篓失败：{exc}")


@router.post("/{image_id}/reparse-models")
def reparse_models(image_id: int, session: Session = Depends(get_session)):
    """用大模型完整解析工作流，更新模型标签与 AI 提示词。"""
    im = session.get(ImageAsset, image_id)
    if im is None or im.is_deleted:
        raise HTTPException(404, "image not found")
    meta = session.exec(
        select(WorkflowMeta).where(WorkflowMeta.image_id == im.id)
    ).first()
    workflow = (meta.workflow_json or meta.prompt_graph_json or "") if meta else ""
    if not workflow:
        raise HTTPException(400, "该图片无可用工作流元数据")

    try:
        parsed = llm.analyze_workflow(workflow, session)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))

    assets = _assets_from_analysis(parsed)
    if meta is None:
        meta = WorkflowMeta(image_id=im.id)
        session.add(meta)
    models = parsed.get("models") or {}
    diffusion = models.get("diffusion_models") or []
    meta.model_name = _basename(_file_of(diffusion[0])) if diffusion else ""

    prompts = parsed.get("prompts") or {}
    meta.ai_prompt = _join_lines(prompts.get("positive"))
    meta.ai_negative_prompt = _join_lines(prompts.get("negative"))
    meta.ai_prompts_json = _dumps_list(prompts.get("positive"))

    meta_service.replace_asset_tags(session, im.id, assets)
    session.commit()

    card = to_card(session, im)
    card["model"] = _basename(meta.model_name)
    return card


@router.post("/{image_id}/rating")
def set_manual_rating(image_id: int, body: dict, session: Session = Depends(get_session)):
    """设置人工评分（1-5）并持久化。"""
    im = session.get(ImageAsset, image_id)
    if im is None or im.is_deleted:
        raise HTTPException(404, "image not found")
    try:
        score = float(body.get("score"))
    except (TypeError, ValueError):
        score = 0
    score = max(1, min(5, round(score)))
    im.rating = score
    session.add(RatingRecord(image_id=im.id, rating_type="manual", score=score))
    session.commit()
    return to_card(session, im)


@router.post("/{image_id}/score")
def score_image(image_id: int, session: Session = Depends(get_session)):
    """用视觉模型给图片打分并持久化（AI 评分）。"""
    im = session.get(ImageAsset, image_id)
    if im is None or im.is_deleted:
        raise HTTPException(404, "image not found")
    try:
        res = llm.score_image(im.abs_path, session)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    im.ai_rating = res["score"]
    session.add(RatingRecord(
        image_id=im.id, rating_type="ai", score=res["score"], reason=res["reason"]
    ))
    session.commit()
    return to_card(session, im)


@router.post("/{image_id}/reverse")
def reverse_prompt(image_id: int, session: Session = Depends(get_session)):
    """用视觉模型对图片反推提示词，写入并返回。"""
    im = session.get(ImageAsset, image_id)
    if im is None or im.is_deleted:
        raise HTTPException(404, "image not found")
    try:
        text = llm.reverse_prompt_image(im.abs_path, session)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    if not text:
        raise HTTPException(502, "视觉模型未生成有效反推结果")

    reverse = _latest(session, ReversePrompt, im.id)
    if reverse is None:
        reverse = ReversePrompt(image_id=im.id)
        session.add(reverse)
    reverse.text = text
    reverse.engine = "vision"
    reverse.model_name = _vision_model_name(session)
    im.prompt_type = "reverse"
    session.commit()
    return {"text": text, "reversePrompt": text}


def _assets_from_analysis(parsed: dict) -> dict[str, list[str]]:
    """把 AI 结构化结果的 models 映射为 {类别: [文件...]} 标签。"""
    models = parsed.get("models") or {}
    return {
        "model": [_file_of(m) for m in models.get("diffusion_models") or []],
        "lora": [_file_of(m) for m in models.get("loras") or []],
        "vae": [_file_of(m) for m in models.get("vaes") or []],
    }


def _file_of(item) -> str:
    return str((item or {}).get("file") or (item or {}).get("path") or "") or ""


def _join_lines(items) -> str:
    if not items:
        return ""
    out = []
    for x in items:
        s = str(x or "").strip()
        if s and s not in out:
            out.append(s)
    return "\n".join(out)


def _dumps_list(items) -> str:
    if not items:
        return ""
    import json

    cleaned = [str(x).strip() for x in items if str(x or "").strip()]
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else ""


def _vision_model_name(session: Session) -> str:
    from ..models import Setting

    row = session.exec(select(Setting).where(Setting.key == "llm_vision_model")).first()
    return row.value if row else ""