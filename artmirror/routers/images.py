"""图片查询与文件服务路由。"""
import re
import threading
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import case, exists, func
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

# 批量 AI 后台任务注册表（内存态）
_BATCH_LOCK = threading.Lock()
_BATCH_SEQ = 0
_BATCH_TASKS: dict[int, dict] = {}


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


def _load_lora_weights(text: str) -> list[dict]:
    """反序列化 LoRA 权重 JSON：[{"name","strength"}] → 前端 loras 列表。"""
    if not text:
        return []
    try:
        import json

        data = json.loads(text)
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if isinstance(item, dict) and item.get("name"):
                out.append({"name": str(item["name"]), "strength": float(item.get("strength") or 0.0)})
        return out
    except Exception:  # noqa: BLE001
        return []


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


def to_cards(session: Session, images: list[ImageAsset]) -> list[dict]:
    """批量组装图库卡片（列表页瘦身版：整页固定 3 次查询，消除逐图 N+1）。"""
    if not images:
        return []
    ids = [im.id for im in images]

    meta_by = {
        m.image_id: m
        for m in session.exec(
            select(WorkflowMeta).where(WorkflowMeta.image_id.in_(ids))
        ).all()
    }

    # 同图多条时取最新：按 id 升序遍历，后写覆盖
    reverse_by: dict[int, ReversePrompt] = {}
    for r in session.exec(
        select(ReversePrompt)
        .where(ReversePrompt.image_id.in_(ids))
        .order_by(ReversePrompt.id)
    ).all():
        reverse_by[r.image_id] = r

    tags_by: dict[int, list[dict]] = {i: [] for i in ids}
    for link, tag in session.exec(
        select(ImageTag, Tag)
        .join(Tag, Tag.id == ImageTag.tag_id)
        .where(ImageTag.image_id.in_(ids), ImageTag.is_deleted == 0)
    ).all():
        tags_by[link.image_id].append(
            {"name": _basename(tag.name), "category": tag.category}
        )

    cards = []
    for im in images:
        meta = meta_by.get(im.id)
        reverse = reverse_by.get(im.id)
        cards.append({
            "id": im.id,
            "folderId": im.folder_id,
            "name": im.file_name,
            "width": im.width,
            "height": im.height,
            "fileSize": im.file_size,
            "rating": im.rating,
            "aiRating": im.ai_rating,
            "prompt": meta.prompt if meta else "",
            "originPrompts": _load_str_list(meta.origin_prompts_json if meta else "") or ([meta.prompt] if meta and meta.prompt else []),
            "aiPrompts": _load_str_list(meta.ai_prompts_json if meta else "") or ([meta.ai_prompt] if meta and meta.ai_prompt else []),
            "aiPrompt": meta.ai_prompt if meta else "",
            "reversePrompt": reverse.text if reverse else None,
            "tags": tags_by[im.id],
            # thumb 按 id 寻址但配了 immutable 长缓存；同一 id 的图内容可变（覆盖/重新导入），
            # 故 URL 需带内容版本（sha256 前 8 位），换图后 URL 变化才能绕过浏览器缓存拿到新缩略图
            "thumb": f"api/images/{im.id}/thumb?v={im.sha256[:8]}" if im.sha256 else f"api/images/{im.id}/thumb",
        })
    return cards


def to_card(session: Session, im: ImageAsset) -> dict:
    """单图完整卡片（详情页 / 单图接口用）：批量瘦身版 + 详情补充字段。"""
    card = to_cards(session, [im])[0]
    meta = session.exec(
        select(WorkflowMeta).where(WorkflowMeta.image_id == im.id)
    ).first()
    trans = session.exec(
        select(PromptTranslation).where(
            PromptTranslation.image_id == im.id,
            PromptTranslation.prompt_kind == "origin",
            PromptTranslation.lang == "zh",
        )
    ).first()
    card["negative"] = meta.negative_prompt if meta else ""
    card["negativePrompts"] = _load_str_list(meta.negative_prompts_json if meta else "")
    card["aiNegative"] = meta.ai_negative_prompt if meta else ""
    card["aiReason"] = _latest_ai_reason(session, im.id)
    card["translationZH"] = trans.text if trans else None
    card["params"] = {
        "steps": meta.steps if meta else None,
        "cfg": meta.cfg if meta else None,
        "sampler": meta.sampler if meta else None,
        "scheduler": meta.scheduler if meta else None,
        "seed": meta.seed if meta else None,
        "denoise": meta.denoise if meta else None,
    }
    return card


def to_detail(session: Session, im: ImageAsset) -> dict:
    card = to_card(session, im)
    meta = session.exec(
        select(WorkflowMeta).where(WorkflowMeta.image_id == im.id)
    ).first()
    card["model"] = _basename(meta.model_name) if meta and meta.model_name else ""
    card["promptGraph"] = meta.prompt_graph_json if meta else ""
    card["workflow"] = meta.workflow_json if meta else ""
    card["path"] = im.file_path
    card["absPath"] = im.abs_path
    # 在用 LoRA 及权重：[{"name","strength"}] —— 前端 chip 展示名称并追加权重
    card["loras"] = _load_lora_weights(meta.loras_json if meta else "")
    # 各提示词源已持久化的中英译文：{kind: {lang: text}}
    translations: dict[str, dict[str, str]] = {}
    for t in session.exec(
        select(PromptTranslation).where(PromptTranslation.image_id == im.id)
    ).all():
        translations.setdefault(t.prompt_kind, {})[t.lang] = t.text
    card["translations"] = translations
    return card


_SEG = "\n<<<SEG>>>\n"  # 多段提示词间的唯一分隔标记（翻译后用于切回分段）


def _kind_prompt_list(session: Session, im: ImageAsset, kind: str) -> list[str]:
    """取某个提示词源的多段主文本（用于互译，保留分段结构）。"""
    if kind == "reverse":
        rev = _latest(session, ReversePrompt, im.id)
        return [rev.text] if rev and rev.text.strip() else []
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
    return [x for x in items if x and x.strip()]


def _split_translation(text: str) -> list[str]:
    """把翻译结果按段间分隔标记切回多段；标记丢失时退回按换行切。"""
    parts = [p.strip() for p in text.split(_SEG) if p.strip()]
    if len(parts) < 2:
        parts = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    return parts or [text.strip()]


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
    parts = _kind_prompt_list(session, im, kind)
    if not parts:
        raise HTTPException(400, "该提示词源暂无内容，无法翻译")

    src = _SEG.join(parts)
    target = _detect_target_lang(src)
    exists = session.exec(
        select(PromptTranslation).where(
            PromptTranslation.image_id == im.id,
            PromptTranslation.prompt_kind == kind,
            PromptTranslation.lang == target,
        )
    ).first()
    if exists is not None:
        return {"texts": _split_translation(exists.text), "lang": target, "cached": True}

    try:
        translated = llm.translate_prompt(src, target, session)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    texts = _split_translation(translated)
    row = PromptTranslation(image_id=im.id, prompt_kind=kind, lang=target, text=_SEG.join(texts))
    session.add(row)
    session.commit()
    return {"texts": texts, "lang": target, "cached": False}


def _tag_match(q: str):
    """生成 EXISTS 断言：某图片是否拥有名称模糊匹配 q 的标签（用于搜索过滤与排序加权）。"""
    like = f"%{q}%"
    return (
        select(1)
        .where(
            ImageTag.tag_id == Tag.id,
            ImageTag.image_id == ImageAsset.id,
            ImageTag.is_deleted == 0,
            Tag.name.like(like),
            Tag.is_deleted == 0,
        )
        .correlate(ImageAsset)
        .exists()
    )


def _filter_images(session: Session, folder_id, tag, q):
    """构建过滤后的基础查询（不含排序/分页）。"""
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
            | _tag_match(q)
        ).distinct()
    return stmt


def _order_for(sort: str) -> list:
    """排序键列表：主键 + id 兜底，保证并列值下 offset 分页确定性。

    time：按图片更新时间倒序。手动导入的单张图片为最新入库（update_time＝now），
    在时间倒序下自然位于列表最前；以 id 兜底保证同一时刻并列时确定有序。
    """
    if sort == "manual":
        return [ImageAsset.rating.desc().nullslast(), ImageAsset.id.desc()]
    if sort == "time":
        return [ImageAsset.update_time.desc(), ImageAsset.id.desc()]
    return [ImageAsset.ai_rating.desc().nullslast(), ImageAsset.id.desc()]


@router.get("")
def list_images(
    folderId: int | None = None,
    tag: str | None = None,
    q: str | None = None,
    sort: str = "ai",
    limit: int = 60,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    """列出图片卡片（分页：过滤 + 排序由后端唯一负责）。"""
    limit = max(1, min(200, limit))
    offset = max(0, offset)
    base = _filter_images(session, folderId, tag, q)
    total = session.exec(select(func.count()).select_from(base.subquery())).one()
    order = _order_for(sort)
    if q:
        # 搜索时：标签命中的图片优先置于最前方，其次才是提示词/文件名命中
        order = [case((_tag_match(q), 0), else_=1)] + order
    imgs = session.exec(
        base.order_by(*order).offset(offset).limit(limit)
    ).all()
    return {
        "items": to_cards(session, imgs),
        "total": total,
        "limit": limit,
        "offset": offset,
        "hasMore": offset + len(imgs) < total,
    }


@router.get("/count")
def count_images(
    folderId: int | None = None,
    kind: str = "",
    session: Session = Depends(get_session),
):
    """统计待处理图片数（用于批量确认）：可排除已处理过的图片。"""
    if folderId:
        base = _filter_images(session, folderId, None, None)
    else:
        base = select(ImageAsset).where(ImageAsset.is_deleted == 0)
    total_all = session.exec(select(func.count()).select_from(base.subquery())).one()
    excl = _batch_excl_sql(session, kind) if kind else None
    if excl is not None:
        pending = session.exec(select(func.count()).select_from(base.where(excl).subquery())).one()
    else:
        pending = total_all
    return {"total": pending, "excluded": total_all - pending, "all": total_all}


def _batch_excl_sql(session: Session, kind: str):
    """批量 AI 的「已处理排除」条件：返回 ImageAsset 上需保留（未处理）的 where 表达式。

    reverse → 排除已有反推提示词；tag → 排除已带属性标签；translate → 排除已有译文；
    score → 排除已有 AI 评分；未知 kind 返回 None（不过滤）。
    """
    if kind == "reverse":
        return ~exists(
            select(1).where(ReversePrompt.image_id == ImageAsset.id).correlate(ImageAsset)
        )
    if kind == "tag":
        return ~exists(
            select(1)
            .where(
                ImageTag.image_id == ImageAsset.id,
                ImageTag.is_deleted == 0,
                Tag.id == ImageTag.tag_id,
                Tag.is_deleted == 0,
                Tag.category == "attr",
            )
            .correlate(ImageAsset)
        )
    if kind == "translate":
        return ~exists(
            select(1).where(PromptTranslation.image_id == ImageAsset.id).correlate(ImageAsset)
        )
    if kind == "score":
        return ImageAsset.ai_rating.is_(None)
    return None


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
        # 缩略图按 sha256 内容寻址，天然不可变：允许浏览器长缓存
        return FileResponse(
            path,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
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
    _delete_image(session, im)
    watcher.bump()
    return {"ok": True, "id": image_id, "moved_to_trash": True}


@router.post("/batch-delete")
def batch_delete_images(ids: list[int] = Body(...), session: Session = Depends(get_session)):
    """批量删除图片：逐张把物理文件移入系统废纸篓并软删入库记录。"""
    if not ids:
        return {"ok": True, "moved": 0, "moved_to_trash": True}
    moved = 0
    for image_id in ids:
        im = session.get(ImageAsset, image_id)
        if im is None or im.is_deleted:
            continue
        _delete_image(session, im)
        moved += 1
    if moved:
        watcher.bump()
    return {"ok": True, "moved": moved, "moved_to_trash": True}


def _delete_image(session: Session, im: ImageAsset) -> None:
    """删除单张图片：物理文件移入废纸篓 + 软删记录 + 回收标签计数（调用方需 commit）。"""
    path = Path(im.abs_path)
    if path.exists():
        _move_to_trash(path)  # 失败会抛出，从而中断删除

    # 软删入库记录并回收标签计数
    im.is_deleted = 1
    for link in session.exec(
        select(ImageTag).where(ImageTag.image_id == im.id)
    ).all():
        tag = session.get(Tag, link.tag_id)
        session.delete(link)
        if tag is not None:
            tag.count = max(0, (tag.count or 0) - 1)
    session.commit()


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


def _first_prompt_kind(session: Session, im: ImageAsset) -> str | None:
    """按 origin → reverse → ai 顺序返回该图首个可翻译的提示词源；无则 None。"""
    for k in ("origin", "reverse", "ai"):
        if _kind_prompt_list(session, im, k):
            return k
    return None


def _batch_ai_one(session: Session, im: ImageAsset, kind: str) -> None:
    """对单图执行一种批量 AI 能力（写入并提交；异常抛出由调用方逐张隔离）。"""
    if kind == "reverse":
        text = llm.reverse_prompt_image(im.abs_path, session)
        if not text:
            raise llm.LLMError("视觉模型未生成有效反推结果")
        rev = _latest(session, ReversePrompt, im.id)
        if rev is None:
            rev = ReversePrompt(image_id=im.id)
            session.add(rev)
        rev.text = text
        rev.engine = "vision"
        rev.model_name = _vision_model_name(session)
        im.prompt_type = "reverse"
    elif kind == "score":
        res = llm.score_image(im.abs_path, session)
        im.ai_rating = res["score"]
        session.add(RatingRecord(
            image_id=im.id, rating_type="ai", score=res["score"], reason=res["reason"]
        ))
    elif kind == "tag":
        prompt = ""
        meta = session.exec(select(WorkflowMeta).where(WorkflowMeta.image_id == im.id)).first()
        if meta and meta.prompt:
            prompt = meta.prompt
        if not prompt:
            rev = _latest(session, ReversePrompt, im.id)
            if rev and rev.text:
                prompt = rev.text
        if not prompt:
            raise llm.LLMError("该图无可分析的提示词")
        tags = llm.extract_prompt_tags(prompt, session)
        for name in tags:
            meta_service._link(session, im.id, name, "attr")
    else:  # translate
        k = _first_prompt_kind(session, im)
        if not k:
            raise llm.LLMError("该图无可用提示词")
        src = _SEG.join(_kind_prompt_list(session, im, k))
        target = _detect_target_lang(src)
        translated = llm.translate_prompt(src, target, session)
        texts = _split_translation(translated)
        row = session.exec(
            select(PromptTranslation).where(
                PromptTranslation.image_id == im.id,
                PromptTranslation.prompt_kind == k,
                PromptTranslation.lang == target,
            )
        ).first()
        if row is None:
            row = PromptTranslation(image_id=im.id, prompt_kind=k, lang=target)
            session.add(row)
        row.text = _SEG.join(texts)
    session.commit()


def _run_batch(bind, tid: int, ids: list[int], kind: str) -> None:
    """后台线程执行批量任务：逐张处理、实时更新进度，可被 cancel 事件终止。"""
    task = _BATCH_TASKS.get(tid)
    if task is None:
        return
    try:
        with Session(bind) as session:
            for im_id in ids:
                if task["cancel"].is_set():
                    break
                im = session.get(ImageAsset, im_id)
                try:
                    if im is not None:
                        _batch_ai_one(session, im, kind)
                        task["ok"] += 1
                except llm.LLMError as exc:
                    if im is not None:
                        task["failed"].append({"id": im.id, "name": im.file_name, "error": str(exc)})
                except Exception as exc:  # noqa: BLE001 — 逐张隔离
                    session.rollback()
                    if im is not None:
                        task["failed"].append({"id": im.id, "name": im.file_name, "error": str(exc)})
                task["done"] += 1
        if task["ok"]:
            watcher.bump()
    finally:
        task["running"] = False


@router.post("/batch-ai")
def batch_ai(body: dict, session: Session = Depends(get_session)):
    """启动批量 AI 任务（异步）：对全部/按目录图片逐个执行反推/打标/互译/评分。

    返回 task_id 与 total，前端轮询任务状态获得实时进度，可调用 stop 终止。
    """
    kind = str((body or {}).get("kind") or "").strip()
    if kind not in ("reverse", "tag", "translate", "score"):
        raise HTTPException(400, "kind 仅支持 reverse / tag / translate / score")
    scope = str((body or {}).get("scope") or "all").strip() or "all"
    if scope == "folder":
        base = _filter_images(session, (body.get("folderId") or None), None, None)
    elif scope == "all":
        base = select(ImageAsset).where(ImageAsset.is_deleted == 0)
    else:
        raise HTTPException(400, "scope 仅支持 all / folder")
    # 排除已处理过的图片（如反推已有反推提示词者）
    excl = _batch_excl_sql(session, kind)
    if excl is not None:
        base = base.where(excl)
    ids = [i.id for i in session.exec(base).all()]
    bind = session.get_bind()

    global _BATCH_SEQ
    with _BATCH_LOCK:
        _BATCH_SEQ += 1
        tid = _BATCH_SEQ
        task = {
            "id": tid, "kind": kind, "total": len(ids), "done": 0, "ok": 0,
            "failed": [], "running": True, "cancel": threading.Event(),
        }
        _BATCH_TASKS[tid] = task
    thread = threading.Thread(target=_run_batch, args=(bind, tid, ids, kind), daemon=True)
    task["thread"] = thread
    thread.start()
    return {"task_id": tid, "kind": kind, "total": len(ids)}


@router.get("/batch-ai/{task_id}")
def batch_ai_status(task_id: int, session: Session = Depends(get_session)):
    """查询批量任务实时状态。"""
    task = _BATCH_TASKS.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    return {
        "task_id": task_id,
        "kind": task["kind"],
        "total": task["total"],
        "done": task["done"],
        "ok": task["ok"],
        "failed": task["failed"],
        "running": task["running"],
        "cancelled": task["cancel"].is_set(),
    }


@router.post("/batch-ai/{task_id}/stop")
def batch_ai_stop(task_id: int, session: Session = Depends(get_session)):
    """终止批量任务：置 cancel 事件，工作线程尽早中断。"""
    task = _BATCH_TASKS.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    task["cancel"].set()
    return {"stopped": True, "task_id": task_id}


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


@router.post("/{image_id}/auto-tag")
def auto_tag_image(image_id: int, session: Session = Depends(get_session)):
    """用文本模型从该图提示词提取属性标签并打标（category=attr，追加合并）。"""
    im = session.get(ImageAsset, image_id)
    if im is None or im.is_deleted:
        raise HTTPException(404, "image not found")

    # 取提示词：优先原生，回退反推
    prompt = ""
    meta = session.exec(
        select(WorkflowMeta).where(WorkflowMeta.image_id == im.id)
    ).first()
    if meta and meta.prompt:
        prompt = meta.prompt
    if not prompt:
        rev = _latest(session, ReversePrompt, im.id)
        if rev and rev.text:
            prompt = rev.text
    if not prompt:
        raise HTTPException(400, "该图无可分析的提示词")

    try:
        tags = llm.extract_prompt_tags(prompt, session)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    if not tags:
        raise HTTPException(502, "文本模型未生成有效标签")

    for name in tags:
        meta_service._link(session, im.id, name, "attr")
    session.commit()
    return {"tags": _image_tags_of(session, im.id, "attr")}


@router.post("/{image_id}/tags")
def add_image_tag(image_id: int, body: dict, session: Session = Depends(get_session)):
    """手动为图片添加属性标签（category=attr）。名称去首尾空白后须非空。"""
    im = session.get(ImageAsset, image_id)
    if im is None or im.is_deleted:
        raise HTTPException(404, "image not found")
    name = str((body or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(400, "标签不能为空")
    meta_service._link(session, im.id, name, "attr")
    session.commit()
    return {"saved": True, "tags": _image_tags_of(session, im.id, "attr")}


@router.delete("/{image_id}/tags")
def remove_image_tag(image_id: int, body: dict, session: Session = Depends(get_session)):
    """删除图片的某个属性标签关联。"""
    im = session.get(ImageAsset, image_id)
    if im is None or im.is_deleted:
        raise HTTPException(404, "image not found")
    name = str((body or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(400, "标签不能为空")
    tag = session.exec(
        select(Tag).where(Tag.name == name, Tag.category == "attr")
    ).first()
    if tag is None:
        raise HTTPException(404, "标签不存在")
    link = session.exec(
        select(ImageTag).where(ImageTag.image_id == im.id, ImageTag.tag_id == tag.id)
    ).first()
    if link is not None:
        session.delete(link)
        tag.count = max(0, (tag.count or 0) - 1)
        session.commit()
    return {"saved": True, "tags": _image_tags_of(session, im.id, "attr")}


def _image_tags_of(session: Session, image_id: int, category: str) -> list[dict]:
    """返回某图指定类别的标签列表。"""
    rows = session.exec(
        select(Tag)
        .join(ImageTag, ImageTag.tag_id == Tag.id)
        .where(
            ImageTag.image_id == image_id,
            Tag.category == category,
            Tag.is_deleted == 0,
        )
        .order_by(Tag.id)
    ).all()
    return [{"name": _basename(t.name), "category": t.category} for t in rows]


@router.post("/{image_id}/prompt")
def update_image_prompt(image_id: int, body: dict, session: Session = Depends(get_session)):
    """保存手编提示词：原生 / AI / 反推 或某源的中英译文。返回最新详情卡片。"""
    im = session.get(ImageAsset, image_id)
    if im is None or im.is_deleted:
        raise HTTPException(404, "image not found")
    target = str(body.get("target") or "").strip()
    if target not in ("origin", "ai", "reverse", "translation"):
        raise HTTPException(400, "target 仅支持 origin / ai / reverse / translation")

    raw = body.get("texts")
    if not isinstance(raw, list):
        raw = [str(body.get("text") or "")]
    texts = [str(x).strip() for x in raw if str(x or "").strip()]

    if target in ("origin", "ai"):
        meta = session.exec(
            select(WorkflowMeta).where(WorkflowMeta.image_id == im.id)
        ).first()
        if meta is None:
            meta = WorkflowMeta(image_id=im.id)
            session.add(meta)
        if target == "origin":
            meta.origin_prompts_json = _dumps_list(texts)
            meta.prompt = texts[0] if texts else ""
        else:
            meta.ai_prompts_json = _dumps_list(texts)
            meta.ai_prompt = texts[0] if texts else ""
    elif target == "reverse":
        rev = _latest(session, ReversePrompt, im.id)
        if rev is None and texts:
            rev = ReversePrompt(image_id=im.id)
            session.add(rev)
        if rev is not None:
            rev.text = "\n".join(texts)
    else:  # translation
        kind = str(body.get("kind") or "").strip()
        lang = str(body.get("lang") or "").strip()
        if kind not in ("origin", "ai", "reverse") or lang not in ("zh", "en"):
            raise HTTPException(400, "translation 需 kind∈origin/ai/reverse 且 lang∈zh/en")
        row = session.exec(
            select(PromptTranslation).where(
                PromptTranslation.image_id == im.id,
                PromptTranslation.prompt_kind == kind,
                PromptTranslation.lang == lang,
            )
        ).first()
        if row is None:
            row = PromptTranslation(image_id=im.id, prompt_kind=kind, lang=lang)
            session.add(row)
        row.text = _SEG.join(texts)

    session.commit()
    watcher.bump()  # 提示词变化须让图库页轮询刷新（返回 gallery 立即生效）
    return to_detail(session, im)


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