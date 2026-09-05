"""JPG 压缩设置读写测试（GET/POST /api/settings 的 compressMode/compressQuality）。

独立 SQLite 文件，仅挂载 settings 路由。
"""
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine

from artmirror.config import settings
from artmirror.database import get_session
from artmirror.routers import settings as settings_router


def _setup(tmp: Path):
    settings.data_dir = str(tmp)
    settings.ensure_dirs()
    engine = create_engine(
        f"sqlite:///{tmp / 't.db'}", connect_args={"check_same_thread": False}, poolclass=NullPool
    )
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(settings_router.router)

    def _session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    return TestClient(app), engine


def test_compress_settings_defaults():
    with tempfile.TemporaryDirectory() as td:
        client, _ = _setup(Path(td))
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["compressMode"] == "new"
        assert data["compressQuality"] == 80


def test_theme_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        client, _ = _setup(Path(td))
        # 默认亮色
        resp = client.get("/api/settings")
        assert resp.json()["theme"] == "light"

        # 写入 claude / dark
        client.post("/api/settings", json={"theme": "claude"})
        assert client.get("/api/settings").json()["theme"] == "claude"
        client.post("/api/settings", json={"theme": "dark"})
        assert client.get("/api/settings").json()["theme"] == "dark"


def test_theme_normalize():
    with tempfile.TemporaryDirectory() as td:
        client, _ = _setup(Path(td))
        # 非法主题归一化为 light；空值同
        client.post("/api/settings", json={"theme": "neon"})
        assert client.get("/api/settings").json()["theme"] == "light"
        client.post("/api/settings", json={"theme": ""})
        assert client.get("/api/settings").json()["theme"] == "light"


def test_compress_settings_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        client, _ = _setup(Path(td))
        resp = client.post("/api/settings", json={"compressMode": "overwrite", "compressQuality": 65})
        assert resp.status_code == 200
        assert resp.json()["saved"] is True

        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["compressMode"] == "overwrite"
        assert data["compressQuality"] == 65


def test_compress_settings_normalize():
    with tempfile.TemporaryDirectory() as td:
        client, _ = _setup(Path(td))
        # 非法 mode 归一化为 overwrite；质量越界收敛到 1-100，非法回默认 80
        client.post("/api/settings", json={"compressMode": "anything", "compressQuality": 999})
        resp = client.get("/api/settings")
        data = resp.json()
        assert data["compressMode"] == "overwrite"
        assert data["compressQuality"] == 100

        client.post("/api/settings", json={"compressQuality": "bad"})
        resp = client.get("/api/settings")
        assert resp.json()["compressQuality"] == 80