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
            from app.routers.images import to_card, to_cards
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
