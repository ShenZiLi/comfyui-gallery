"""scanner + meta 集成测试（内存库 + 临时目录）。

验证：扫描入库、meta 解析、标签生成、增量跳过、软删。
"""
import base64
import json
import tempfile
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import settings
from app.models import Folder, ImageAsset, Tag, WorkflowMeta
from app.services import scanner

GRAPH = {
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "m.safetensors"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "snowy fox macro", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry lowres", "clip": ["4", 1]}},
    "8": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 20, "cfg": 6.5,
                                                "sampler_name": "euler", "scheduler": "normal",
                                                "positive": ["6", 0], "negative": ["7", 0]}},
}


def _png(path: Path, tone: int = 30):
    pi = PngInfo()
    enc = base64.b64encode(json.dumps(GRAPH).encode()).decode("latin-1")
    pi.add_text("workflow", enc)
    pi.add_text("prompt", enc)
    Image.new("RGB", (256, 320), (tone, 60, 90)).save(str(path), format="PNG", pnginfo=pi)


def _engine(tmp: Path):
    settings.data_dir = str(tmp)
    settings.ensure_dirs()
    engine = create_engine(f"sqlite:///{tmp / 't.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_scan_and_ingest():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        root = td / "outputs"; root.mkdir()
        sub = root / "a"; sub.mkdir()
        _png(sub / "ComfyUI_001_.png", tone=40)
        _png(root / "ComfyUI_002_.png", tone=60)

        engine = _engine(td / "data")
        with Session(engine) as session:
            stats = scanner.scan(session, root)
            assert stats.new == 2
            assert stats.parsed == 2
            assert stats.errors == []

            images = session.exec(select(ImageAsset)).all()
            assert len(images) == 2
            metas = session.exec(select(WorkflowMeta)).all()
            assert all(m.prompt == "snowy fox macro" for m in metas)
            tags = session.exec(select(Tag)).all()
            assert [t.name for t in tags if t.category == "model"] == ["m.safetensors"]
            folders = session.exec(select(Folder)).all()
            assert any(f.path == "a" for f in folders)

            # 增量：再扫一次应全部跳过
            stats2 = scanner.scan(session, root)
            assert stats2.skipped == 2 and stats2.new == 0

    settings.data_dir = "/Users/shen/Studio/Code/ArtMirror/data"  # 还原（尽量）


def test_track_removal():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        root = td / "outputs"; root.mkdir()
        _png(root / "gone.png")
        engine = _engine(td / "data")
        with Session(engine) as session:
            stats = scanner.scan(session, root)
            assert stats.new == 1
        (root / "gone.png").unlink()
        with Session(engine) as session:
            stats2 = scanner.scan(session, root)
            assert stats2.removed == 1
            im = session.exec(select(ImageAsset)).one()
            assert im.is_deleted == 1
    settings.data_dir = "/Users/shen/Studio/Code/ArtMirror/data"