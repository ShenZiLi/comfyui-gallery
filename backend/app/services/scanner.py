"""图片扫描与入库服务。

递归扫描配置根目录，sha256 去重、mtime+size 增量更新、生成缩略图，
并把 ComfyUI meta 解析后落库；对已消失文件做软删除。
"""
from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from sqlmodel import Session, select

from ..config import settings
from ..models import Folder, ImageAsset, Setting
from ..parsers.comfyui_parser import parse_bytes
from . import meta_service

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
THUMB_SIZE = (480, 600)


@dataclass
class ScanStats:
    """扫描统计。"""

    new: int = 0
    updated: int = 0
    skipped: int = 0
    removed: int = 0
    parsed: int = 0
    errors: list[str] = field(default_factory=list)


def get_scan_root(session: Session) -> Path | None:
    """读取扫描根目录（优先 setting 表，其次环境配置）。"""
    row = session.exec(select(Setting).where(Setting.key == "scan_root")).first()
    if row and row.value:
        return Path(row.value)
    return Path(settings.scan_root) if settings.scan_root else None


def save_scan_root(session: Session, root: str) -> None:
    """持久化扫描根目录。"""
    row = session.exec(select(Setting).where(Setting.key == "scan_root")).first()
    if row is None:
        row = Setting(key="scan_root", value=root)
        session.add(row)
    else:
        row.value = root
    session.commit()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_thumb(data: bytes) -> bytes:
    """生成 WebP 缩略图。"""
    with Image.open(io.BytesIO(data)) as img:
        img.thumbnail(THUMB_SIZE)
        out = io.BytesIO()
        img.save(out, format="WEBP", quality=82)
        return out.getvalue()


def _ensure_folders(session: Session, root: Path) -> dict[str, int]:
    """扫描目录并建立 Folder 树，返回 {相对路径: folder_id}。"""
    mapping: dict[str, int] = {"": None}
    for f in session.exec(select(Folder)).all():
        mapping[f.path] = f.id
    for dirpath, dirnames, _ in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        rel_norm = "" if rel == "." else rel.replace(os.sep, "/")
        if rel_norm in mapping:
            continue
        parent = os.path.dirname(rel_norm)
        parent_id = mapping.get(parent)
        f = Folder(name=os.path.basename(dirpath) or root.name, path=rel_norm, parent_id=parent_id)
        session.add(f)
        session.flush()
        mapping[rel_norm] = f.id
    session.commit()
    return mapping


def scan(session: Session, root: Path) -> ScanStats:
    """执行一次全量/增量扫描，返回统计。"""
    stats = ScanStats()
    root = Path(root).resolve()
    if not root.is_dir():
        stats.errors.append(f"目录不存在: {root}")
        return stats
    settings.ensure_dirs()

    folder_ids = _ensure_folders(session, root)
    seen_paths: set[str] = set()

    for dirpath, dirnames, files in os.walk(root):
        # 跳过隐藏目录
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in files:
            if Path(name).suffix.lower() not in IMAGE_EXTS:
                continue
            full = Path(dirpath) / name
            rel_norm = os.path.relpath(full, root).replace(os.sep, "/")
            seen_paths.add(rel_norm)

            existing = session.exec(
                select(ImageAsset).where(
                    ImageAsset.file_path == rel_norm, ImageAsset.is_deleted == 0
                )
            ).first()

            mtime = full.stat().st_mtime
            size = full.stat().st_size

            if existing and existing.file_size == size and abs(existing.file_mtime - mtime) < 1e-6:
                stats.skipped += 1
                continue

            try:
                data = full.read_bytes()
                sha = _hash_bytes(data)
            except OSError as exc:
                stats.errors.append(str(exc))
                continue

            # sha 去重：同内容不再入库
            dup = session.exec(
                select(ImageAsset).where(
                    ImageAsset.sha256 == sha,
                    ImageAsset.file_path != rel_norm,
                    ImageAsset.is_deleted == 0,
                )
            ).first()

            result = parse_bytes(data)
            thumb_path = settings.thumbs_dir / f"{sha}.webp"
            try:
                thumb_bytes = _make_thumb(data)
                thumb_path.write_bytes(thumb_bytes)
                thumb_ok = 1
            except Exception:  # noqa: BLE001
                thumb_ok = 0

            if existing is None and dup is None:
                image = ImageAsset(
                    folder_id=folder_ids.get(os.path.dirname(rel_norm)),
                    file_name=full.name,
                    file_path=rel_norm,
                    abs_path=str(full),
                    sha256=sha,
                    width=result.width,
                    height=result.height,
                    file_size=size,
                    file_mtime=mtime,
                    thumb_ok=thumb_ok,
                )
                session.add(image)
                session.flush()
                if result.prompt_graph or result.workflow:
                    meta_service.ingest(session, image, result)
                    stats.parsed += 1
                stats.new += 1
            else:
                if existing is None:
                    existing = dup
                existing.file_name = full.name
                existing.abs_path = str(full)
                existing.width = result.width
                existing.height = result.height
                existing.file_size = size
                existing.file_mtime = mtime
                existing.thumb_ok = thumb_ok
                existing.sha256 = sha
                existing.is_deleted = 0
                if result.prompt_graph or result.workflow:
                    meta_service.ingest(session, existing, result)
                    stats.parsed += 1
                stats.updated += 1
            session.commit()

    # 软删：库中在根内但本次未扫描到的
    root_prefix = str(root.resolve()).rstrip("/")
    for im in session.exec(
        select(ImageAsset).where(
            ImageAsset.is_deleted == 0, ImageAsset.abs_path.like(f"{root_prefix}%")
        )
    ).all():
        if im.file_path not in seen_paths:
            im.is_deleted = 1
            stats.removed += 1
    session.commit()
    return stats