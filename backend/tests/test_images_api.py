"""图片列表接口测试（批量组装 / 分页 / 卡片瘦身 / 缩略图缓存头）。

只挂载 images 路由（避免 watcher 与静态托管副作用），DB 为独立 SQLite 文件。
"""
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings
from app.database import get_session
from app.models import (
    ImageAsset, ImageTag, PromptTranslation, RatingRecord, ReversePrompt, Tag, WorkflowMeta,
)
from app.routers import images
from app.routers.images import to_card, to_cards


def _setup(tmp: Path):
    settings.data_dir = str(tmp)
    settings.ensure_dirs()
    engine = create_engine(
        f"sqlite:///{tmp / 't.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(images.router)

    def _session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    return TestClient(app), engine


def _seed(session: Session, n: int = 3) -> list[ImageAsset]:
    """造 n 张图：meta / 两条反推（最新生效）/ 译文 / AI 评分理由 / 标签。"""
    ims = []
    for i in range(n):
        im = ImageAsset(
            file_name=f"i{i}.png", file_path=f"/x/i{i}.png", abs_path=f"/x/i{i}.png",
            sha256=f"{i:064x}", width=64, height=64, file_size=100,
        )
        session.add(im)
        session.flush()
        session.add(WorkflowMeta(
            image_id=im.id, prompt=f"p{i} masterpiece", negative_prompt="neg",
            origin_prompts_json='["pa","pb"]', steps=20, cfg=7, seed=i,
        ))
        session.add(ReversePrompt(image_id=im.id, text="rev-old"))
        session.add(ReversePrompt(image_id=im.id, text="rev-new"))
        session.add(PromptTranslation(image_id=im.id, prompt_kind="origin", lang="zh", text="译文"))
        session.add(RatingRecord(image_id=im.id, rating_type="ai", score=90, reason="好看"))
        ims.append(im)
    tag = Tag(name="model-x", category="model")
    session.add(tag)
    session.flush()
    for im in ims:
        session.add(ImageTag(image_id=im.id, tag_id=tag.id))
    session.commit()
    return ims


def test_to_cards_batch_and_full_card():
    with tempfile.TemporaryDirectory() as td:
        _, engine = _setup(Path(td))
        with Session(engine) as s:
            ims = _seed(s, 2)
            cards = to_cards(s, ims)
            assert [c["id"] for c in cards] == [im.id for im in ims]
            c = cards[0]
            assert c["reversePrompt"] == "rev-new"          # 取最新一条
            assert c["tags"] == [{"name": "model-x", "category": "model"}]
            assert c["originPrompts"] == ["pa", "pb"]
            assert c["thumb"] == f"/api/images/{c['id']}/thumb"
            for absent in ("negative", "negativePrompts", "aiNegative", "aiReason", "translationZH", "params"):
                assert absent not in c                      # 列表瘦身字段
            full = to_card(s, ims[0])
            for present in ("negative", "negativePrompts", "aiNegative", "aiReason", "translationZH", "params"):
                assert present in full
            assert full["translationZH"] == "译文"
            assert full["aiReason"] == "好看"
            assert full["params"]["steps"] == 20
            # 批量组装边界：空列表与无 meta 图片
            assert to_cards(s, []) == []


def test_list_pagination_defaults_and_caps():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            _seed(s, 5)
        body = client.get("/api/images").json()
        assert body["total"] == 5 and len(body["items"]) == 5 and body["hasMore"] is False
        assert body["limit"] == 60 and body["offset"] == 0
        body = client.get("/api/images?limit=2").json()
        assert len(body["items"]) == 2 and body["hasMore"] is True
        body = client.get("/api/images?limit=2&offset=4").json()
        assert len(body["items"]) == 1 and body["hasMore"] is False
        assert client.get("/api/images?limit=9999").json()["limit"] == 200  # 上限截断


def test_list_filter_sort_and_slim():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            _seed(s, 3)
        body = client.get("/api/images?q=p1").json()  # 命中 1 张
        assert body["total"] == 1 and body["items"][0]["prompt"] == "p1 masterpiece"
        ids = [c["id"] for c in client.get("/api/images?sort=time").json()["items"]]
        assert ids == sorted(ids, reverse=True)
        c = client.get("/api/images").json()["items"][0]
        for absent in ("negative", "negativePrompts", "aiNegative", "aiReason", "translationZH", "params"):
            assert absent not in c


def test_detail_keeps_full_fields():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            ims = _seed(s, 1)
            image_id = ims[0].id  # session 关闭后过期属性不可访问，块内先取出
        d = client.get(f"/api/images/{image_id}").json()
        for present in ("negative", "params", "aiReason", "translationZH", "workflow", "translations"):
            assert present in d


def test_to_cards_no_meta_defaults():
    with tempfile.TemporaryDirectory() as td:
        _, engine = _setup(Path(td))
        with Session(engine) as s:
            im = ImageAsset(file_name="bare.png", file_path="/x/bare.png", abs_path="/x/bare.png",
                            sha256="e" * 64, width=8, height=8, file_size=1)
            s.add(im); s.commit()
            c = to_cards(s, [im])[0]
            assert c["prompt"] == "" and c["reversePrompt"] is None and c["originPrompts"] == []
            assert c["tags"] == [] and c["aiPrompt"] == ""


def test_pagination_tiebreaker_stable():
    """并列排序键（全 NULL ai_rating）下翻页不重叠不遗漏。"""
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            _seed(s, 6)  # 全部 ai_rating=NULL
        p1 = client.get("/api/images?sort=ai&limit=3").json()
        p2 = client.get("/api/images?sort=ai&limit=3&offset=3").json()
        ids1 = {c["id"] for c in p1["items"]}
        ids2 = {c["id"] for c in p2["items"]}
        assert not (ids1 & ids2)
        assert len(ids1 | ids2) == 6
        assert ids1 | ids2 == {c["id"] for c in p1["items"] + p2["items"]}


def test_pagination_clamps_and_overflow():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            _seed(s, 2)
        assert client.get("/api/images?limit=0").json()["limit"] == 1      # 下界
        assert client.get("/api/images?offset=-5").json()["offset"] == 0  # 负 offset
        over = client.get("/api/images?limit=10&offset=99").json()        # 超总量
        assert over["items"] == [] and over["hasMore"] is False


def test_pagination_with_tag_and_folder_filters():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            _seed(s, 4)
        # tag 过滤 × 分页（_seed 中每图都挂 model-x 标签）
        b = client.get("/api/images?tag=model-x&limit=2").json()
        assert b["total"] == 4 and len(b["items"]) == 2 and b["hasMore"] is True
        # 无 folder 记录时 folderId=999 过滤为空
        b2 = client.get("/api/images?folderId=999").json()
        assert b2["total"] == 0 and b2["items"] == []
