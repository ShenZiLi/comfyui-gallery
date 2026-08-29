"""聚合接口测试（组列表分页 / coverThumbs / 成员懒加载 / 页内相似聚类）。"""
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings
from app.database import get_session
from app.models import ImageAsset, WorkflowMeta
from app.routers import aggregate


def _setup(tmp: Path):
    settings.data_dir = str(tmp)
    settings.ensure_dirs()
    engine = create_engine(
        f"sqlite:///{tmp / 't.db'}", connect_args={"check_same_thread": False}, poolclass=NullPool
    )
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(aggregate.router)

    def _session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    return TestClient(app), engine


def _seed_texts(session: Session, texts: list[str]) -> None:
    n = 0
    for text in texts:
        n += 1
        im = ImageAsset(
            file_name=f"g{n}.png", file_path=f"/x/g{n}.png", abs_path=f"/x/g{n}.png",
            sha256=f"{n:064x}", width=64, height=64, file_size=10, ai_rating=float(n),
        )
        session.add(im)
        session.flush()
        session.add(WorkflowMeta(image_id=im.id, prompt=text))
    session.commit()


def _seed(session: Session) -> None:
    # A 组 8 张（验证封面截断）、B 组 2 张、C 组 1 张
    _seed_texts(session, ["prompt alpha common"] * 8 + ["prompt beta common"] * 2 + ["prompt gamma common"])


def test_by_prompt_paged_groups():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            _seed(s)
        body = client.get("/api/aggregate/by-prompt?limit=2").json()
        assert set(body) >= {"items", "total", "limit", "offset", "hasMore"}
        assert body["total"] == 3 and len(body["items"]) == 2 and body["hasMore"] is True
        g = body["items"][0]
        assert set(g) == {"id", "title", "kind", "count", "maxScore", "coverThumbs"}
        assert g["count"] == 1 and g["title"] == "prompt gamma common"  # maxScore 最大者在前
        body2 = client.get("/api/aggregate/by-prompt?limit=2&offset=2").json()
        assert len(body2["items"]) == 1 and body2["hasMore"] is False


def test_cover_thumbs_capped_at_six():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            _seed(s)
        items = client.get("/api/aggregate/by-prompt?limit=10").json()["items"]
        big = next(g for g in items if g["count"] == 8)
        assert len(big["coverThumbs"]) == 6
        assert all(m["thumb"].startswith("/api/images/") for m in big["coverThumbs"])


def test_group_members_paged():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            _seed(s)
        items = client.get("/api/aggregate/by-prompt?limit=10").json()["items"]
        big = next(g for g in items if g["count"] == 8)
        m = client.get("/api/aggregate/by-prompt/members", params={"group": big["id"], "limit": 5}).json()
        assert m["total"] == 8 and len(m["items"]) == 5 and m["hasMore"] is True
        m2 = client.get("/api/aggregate/by-prompt/members", params={"group": big["id"], "limit": 5, "offset": 5}).json()
        assert len(m2["items"]) == 3 and m2["hasMore"] is False
        r = client.get("/api/aggregate/by-prompt/members", params={"group": "nope"})
        assert r.status_code == 404


def test_similar_clusters_within_page():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            _seed_texts(s, [
                "a beautiful scenic mountain landscape",
                "a beautiful scenic mountain landscapes",
                "totally different city street photo",
            ])
        body = client.get("/api/aggregate/by-prompt?kind=similar&limit=10").json()
        assert body["total"] == 3  # exact 组仍为 3
        assert len(body["items"]) == 2  # 前两条相似（ratio≈0.985 ≥ 0.92）合并
        merged = next(g for g in body["items"] if g["kind"] == "similar")
        assert merged["count"] == 2
