"""聚合与维度分组路由（需求 7/11）。"""
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..database import get_session
from ..models import ImageAsset, Tag, ImageTag, WorkflowMeta
from .images import to_card

router = APIRouter(prefix="/api/aggregate", tags=["aggregate"])


def _normalize(p: str) -> str:
    return " ".join((p or "").lower().split())


@router.get("/by-prompt")
def aggregate_by_prompt(kind: str = "exact", session: Session = Depends(get_session)):
    """按提示词分组（exact=相同；similar=相似，MVP 用 SequenceMatcher）。"""
    rows = session.exec(
        select(ImageAsset, WorkflowMeta)
        .join(WorkflowMeta, WorkflowMeta.image_id == ImageAsset.id)
        .where(
            ImageAsset.is_deleted == 0,
            WorkflowMeta.prompt != "",
        )
    ).all()

    groups: dict[str, list] = {}
    for im, meta in rows:
        groups.setdefault(_normalize(meta.prompt), []).append(im)

    ordered = sorted(groups.items(), key=lambda kv: -max(
        (im.ai_rating or 0) for im in kv[1]
    ))
    out = []
    titles = {}
    for key, members in ordered:
        sorted_members = sorted(members, key=lambda m: -(m.ai_rating or 0))
        title = session.exec(
            select(WorkflowMeta).where(
                WorkflowMeta.image_id == sorted_members[0].id
            )
        ).first().prompt
        titles[key] = title
        out.append({
            "id": key,
            "title": title,
            "kind": "exact",
            "count": len(sorted_members),
            "maxScore": sorted_members[0].ai_rating or 0,
            "cover": to_card(session, sorted_members[0]),
            "members": [to_card(session, m) for m in sorted_members],
        })

    if kind == "similar":
        out = _cluster_similar(out, titles)
    session.rollback()
    return out


def _cluster_similar(groups: list[dict], titles: dict) -> list[dict]:
    """序列相似聚类（MVP）：按相似度阈值建边 + 并查集。"""
    import difflib

    parent = list(range(len(groups)))
    ordering = [g["id"] for g in groups]

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    threshold = 0.92
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            ratio = difflib.SequenceMatcher(
                None, titles[groups[i]["id"]], titles[groups[j]["id"]]
            ).ratio()
            if ratio >= threshold:
                union(i, j)

    clusters: dict[int, list[dict]] = {}
    for i, g in enumerate(groups):
        clusters.setdefault(find(i), []).append(g)

    out = []
    for idx, members in clusters.items():
        all_members = [m for g in members for m in g["members"]]
        all_members.sort(key=lambda m: -(m["aiRating"] or 0))
        cover = all_members[0] if all_members else None
        out.append({
            "id": f"sim-{idx}",
            "title": members[0]["title"],
            "kind": "similar",
            "count": len(all_members),
            "maxScore": cover["aiRating"] or 0 if cover else 0,
            "cover": cover,
            "samples": [g["title"] for g in members[:3]],
            "members": all_members,
        })
    out.sort(key=lambda g: -g["maxScore"])
    return out


@router.get("/dimensions")
def dimension_groups(session: Session = Depends(get_session)):
    """按模型/LoRA/VAE/风格等维度分组。"""
    result = {}
    rows = session.exec(
        select(Tag, ImageTag)
        .join(ImageTag, ImageTag.tag_id == Tag.id)
        .where(Tag.is_deleted == 0, Tag.category != "special")
        .order_by(Tag.category, Tag.name)
    ).all()
    for tag, link in rows:
        bucket = result.setdefault(tag.category, {})
        im = session.get(ImageAsset, link.image_id)
        if im is None or im.is_deleted:
            continue
        bucket_list = bucket.setdefault(tag.name, [])
        bucket_list.append(to_card(session, im))
    return [
        {"category": cat, "items": [
            {"name": name, "category": cat, "count": len(items), "members": items}
            for name, items in members.items()
        ]}
        for cat, members in result.items()
    ]