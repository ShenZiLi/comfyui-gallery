"""聚合与维度分组路由（需求 7/11）。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, case, cast, func
from sqlmodel import Session, select

from ..database import get_session
from ..models import ImageAsset, Tag, ImageTag, WorkflowMeta
from .images import to_cards

router = APIRouter(prefix="/api/aggregate", tags=["aggregate"])


def _normalize(p: str) -> str:
    return " ".join((p or "").lower().split())


def _first_prompt(meta) -> str:
    """取提示词列表中的第一条作为聚合主维度（旧的未带列表则回退 prompt）。"""
    return _first_prompt_of(meta.prompt if meta else "", meta.origin_prompts_json if meta else "")


def _first_prompt_of(prompt: str, origin_json: str) -> str:
    if origin_json:
        try:
            import json

            arr = json.loads(origin_json)
            if isinstance(arr, list) and arr and str(arr[0]).strip():
                return str(arr[0]).strip()
        except Exception:  # noqa: BLE001
            pass
    return prompt or ""


# 聚合维度取提示词列表第一条（json_extract 下推到 SQL，万行级别省去逐行 json.loads）；
# 无效 JSON / 空数组 / 空串回退 prompt。
_FP_SQL = case(
    (
        func.json_valid(WorkflowMeta.origin_prompts_json) == 1,
        func.coalesce(
            func.nullif(
                func.trim(cast(func.json_extract(WorkflowMeta.origin_prompts_json, "$[0]"), String)),
                "",
            ),
            WorkflowMeta.prompt,
        ),
    ),
    else_=WorkflowMeta.prompt,
)


def _group_all(session: Session) -> list[dict]:
    """按提示词首条分组（内存 O(n)），按 maxScore 降序返回组列表。

    只取轻量列（避免整表 ORM 实体化开销）；成员按 ai_rating 降序、id 降序确定排序。
    """
    rows = session.exec(
        select(
            ImageAsset.id,
            ImageAsset.file_name,
            ImageAsset.ai_rating,
            _FP_SQL,
        )
        .join(WorkflowMeta, WorkflowMeta.image_id == ImageAsset.id)
        .where(
            ImageAsset.is_deleted == 0,
            WorkflowMeta.prompt != "",
        )
    ).all()

    groups: dict[str, dict] = {}
    key_cache: dict[str, str] = {}
    for im_id, file_name, ai_rating, fp in rows:
        if not fp:
            continue
        key = key_cache.get(fp)
        if key is None:
            key = key_cache[fp] = _normalize(fp)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"key": key, "title": fp, "members": []}
        g["members"].append({"id": im_id, "name": file_name, "aiRating": ai_rating or 0})

    out = list(groups.values())
    for g in out:
        g["members"].sort(key=lambda m: (-m["aiRating"], -m["id"]))
    out.sort(key=lambda g: -g["members"][0]["aiRating"])
    return out


def _group_payload(g: dict) -> dict:
    """组卡片：封面行直接可渲染，不携带全部成员。"""
    members = g["members"]
    return {
        "id": g["key"],
        "title": g["title"],
        "kind": "exact",
        "count": len(members),
        "maxScore": members[0]["aiRating"],
        "coverThumbs": [
            {"id": m["id"], "name": m["name"], "thumb": f"/api/images/{m['id']}/thumb"}
            for m in members[:6]
        ],
    }


@router.get("/by-prompt")
def aggregate_by_prompt(
    kind: str = "exact",
    limit: int = 20,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    """按提示词分组（分页返回组列表；exact=相同，similar=页内相似聚类）。"""
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    all_groups = _group_all(session)
    total = len(all_groups)
    page = all_groups[offset:offset + limit]
    items = [_group_payload(g) for g in page]
    if kind == "similar":
        items = _cluster_page(items)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "hasMore": offset + len(page) < total,
    }


@router.get("/by-prompt/members")
def group_members(
    group: str,
    limit: int = 24,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    """某提示词组的成员（展开组时懒加载、分页）。"""
    limit = max(1, min(200, limit))
    offset = max(0, offset)
    for g in _group_all(session):
        if g["key"] != group:
            continue
        members = g["members"]
        page = members[offset:offset + limit]
        ids = [m["id"] for m in page]
        by_id = {im.id: im for im in session.exec(
            select(ImageAsset).where(ImageAsset.id.in_(ids))
        ).all()}
        ordered = [by_id[i] for i in ids if i in by_id]
        return {
            "items": to_cards(session, ordered),
            "total": len(members),
            "limit": limit,
            "offset": offset,
            "hasMore": offset + len(page) < len(members),
        }
    raise HTTPException(404, "group not found")


def _cluster_page(items: list[dict]) -> list[dict]:
    """页内相似聚类：仅对当前页的组两两比较（页 ≤ 100 组，毫秒级）。

    相似簇的 id 取首个子组键；members 懒加载只返回该键的成员（UI 当前仅用 exact）。
    """
    import difflib

    n = len(items)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    threshold = 0.92
    for i in range(n):
        for j in range(i + 1, n):
            ratio = difflib.SequenceMatcher(None, items[i]["title"], items[j]["title"]).ratio()
            if ratio >= threshold:
                union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    out = []
    for idxs in clusters.values():
        first = items[idxs[0]]
        if len(idxs) == 1:
            out.append(first)
            continue
        thumbs = []
        for i in idxs:
            thumbs.extend(items[i]["coverThumbs"])
        out.append({
            "id": first["id"],
            "title": first["title"],
            "kind": "similar",
            "count": sum(items[i]["count"] for i in idxs),
            "maxScore": max(items[i]["maxScore"] for i in idxs),
            "coverThumbs": thumbs[:6],
        })
    out.sort(key=lambda g: -g["maxScore"])
    return out


@router.get("/dimensions")
def dimension_groups(session: Session = Depends(get_session)):
    """按模型/LoRA/VAE/风格等维度分组。"""
    rows = session.exec(
        select(Tag, ImageTag)
        .join(ImageTag, ImageTag.tag_id == Tag.id)
        .where(Tag.is_deleted == 0, Tag.category != "special")
        .order_by(Tag.category, Tag.name)
    ).all()
    if not rows:
        return []
    ids = sorted({link.image_id for _, link in rows})
    imgs = session.exec(
        select(ImageAsset).where(ImageAsset.id.in_(ids), ImageAsset.is_deleted == 0)
    ).all()
    cards_by = {c["id"]: c for c in to_cards(session, imgs)}
    result: dict[str, dict[str, list[dict]]] = {}
    for tag, link in rows:
        card = cards_by.get(link.image_id)
        if card is None:
            continue
        result.setdefault(tag.category, {}).setdefault(tag.name, []).append(card)
    return [
        {"category": cat, "items": [
            {"name": name, "category": cat, "count": len(items), "members": items}
            for name, items in members.items()
        ]}
        for cat, members in result.items()
    ]