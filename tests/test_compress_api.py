"""图片无损压缩接口测试（单张 new / overwrite）。

只挂载 compress 路由，DB 为独立 SQLite 文件；依赖 settings.data_dir 解析导入目录。
"""
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine

from artmirror.config import settings
from artmirror.database import get_session, reset_engine
from artmirror.models import ImageAsset, Setting
from artmirror.routers import compress


def _make_gradient_png(path: Path, size=(800, 600)) -> int:
    """生成一张平滑渐变 RGB PNG（level0 重存 → 体积大，便于压缩变小）。"""
    small = Image.new("RGB", (8, 8))
    px = small.load()
    for y in range(8):
        for x in range(8):
            px[x, y] = (x * 32, y * 32, (x + y) * 16)
    img = small.resize(size, Image.BILINEAR)
    img.save(str(path), "PNG", compress_level=0)
    return path.stat().st_size


def _setup(tmp: Path):
    settings.data_dir = str(tmp)
    settings.ensure_dirs()
    engine = create_engine(
        f"sqlite:///{tmp / 't.db'}", connect_args={"check_same_thread": False}, poolclass=NullPool
    )
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(compress.router)

    def _session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    return TestClient(app), engine


def _seed(session: Session, png: Path, mode: str, keep_meta: str = "true") -> int:
    session.add(Setting(key="compress_mode", value=mode))
    session.add(Setting(key="compress_keep_meta", value=keep_meta))
    im = ImageAsset(
        file_name=png.name,
        file_path=str(png),
        abs_path=str(png),
        sha256="0" * 64,
        width=800,
        height=600,
        file_size=png.stat().st_size,
    )
    session.add(im)
    session.commit()
    return im.id


def test_single_compress_new():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            src = Path(td) / "origin.png"
            _make_gradient_png(src)
            image_id = _seed(s, src, mode="new")
            original = src.stat().st_size
        resp = client.post(f"/api/images/{image_id}/compress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["saved"] is True
        assert data["original"] == original
        assert data["compressed"] < data["original"]
        assert data["new_file"] and Path(data["new_file"]).is_file()
        reset_engine()  # 释放后台扫描持有的全局 engine 连接，便于临时目录清理


def test_single_compress_overwrite():
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            src = Path(td) / "overwrite.png"
            _make_gradient_png(src)
            image_id = _seed(s, src, mode="overwrite")
            original = src.stat().st_size
        resp = client.post(f"/api/images/{image_id}/compress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["saved"] is True
        assert data["new_file"] == str(src)
        assert Path(data["new_file"]).is_file()
        assert Path(data["new_file"]).stat().st_size < original


def test_batch_compress_raw_array_body():
    """批量接口 body 为裸数组（如 [id]），与前端 Api.batchCompress 用法一致。"""
    with tempfile.TemporaryDirectory() as td:
        client, engine = _setup(Path(td))
        with Session(engine) as s:
            src = Path(td) / "batch.png"
            _make_gradient_png(src)
            image_id = _seed(s, src, mode="new")
        resp = client.post("/api/images/batch-compress", json=[image_id])
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["saved_count"] == 1
        assert data["results"][0]["saved"] is True
        assert data["results"][0]["new_file"] and Path(data["results"][0]["new_file"]).is_file()
        reset_engine()