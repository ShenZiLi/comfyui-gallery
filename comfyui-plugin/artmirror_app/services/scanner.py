"""图片扫描与入库服务。

递归扫描多个配置根目录，sha256 去重、mtime+size 增量更新、生成缩略图，
并把 ComfyUI meta 解析后落库；对已消失文件做软删除。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from sqlmodel import Session, select
from sqlalchemy.exc import IntegrityError

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

    def merge(self, other: "ScanStats") -> "ScanStats":
        self.new += other.new
        self.updated += other.updated
        self.skipped += other.skipped
        self.removed += other.removed
        self.parsed += other.parsed
        self.errors.extend(other.errors)
        return self


def get_scan_roots(session: Session) -> list[Path]:
    """读取多个扫描根目录（优先 setting 表，其次环境配置）。"""
    row = session.exec(select(Setting).where(Setting.key == "scan_roots")).first()
    if row and row.value:
        try:
            roots = json.loads(row.value)
            return [Path(r) for r in roots if r]
        except (json.JSONDecodeError, TypeError):
            pass
    # 兼容旧的单目录字段
    old = session.exec(select(Setting).where(Setting.key == "scan_root")).first()
    if old and old.value:
        return [Path(old.value)]
    if settings.scan_root:
        return [Path(settings.scan_root)]
    return []


def save_scan_roots(session: Session, roots: list[str]) -> None:
    """持久化多个扫描根目录。"""
    cleaned = [r.strip() for r in roots if r and r.strip()]
    row = session.exec(select(Setting).where(Setting.key == "scan_roots")).first()
    if row is None:
        row = Setting(key="scan_roots", value="")
        session.add(row)
    row.value = json.dumps(cleaned, ensure_ascii=False)
    session.commit()


def _nested_root_prefixes(session: Session, root: Path) -> list[str]:
    """返回注册在 root 目录之下的其他扫描根目录（规范化小写前缀，不带尾部 /）。

    用于避免嵌套根目录被父根重复扫描：父根跳过其子树内的嵌套根文件，
    软删除也跳过属于嵌套根的行（由嵌套根自己管理），否则同一物理文件
    每轮都被判定为「更新/移除」，导致同步版本号持续递增。
    """
    root_norm = str(root.resolve()).replace("\\", "/").rstrip("/").lower()
    prefixes: list[str] = []
    for r in get_scan_roots(session):
        rn = str(r.resolve()).replace("\\", "/").rstrip("/").lower()
        if rn != root_norm and rn.startswith(root_norm + "/"):
            prefixes.append(rn)
    return prefixes


def _under_prefix(path, prefixes: list[str]) -> bool:
    """规范化路径（/ 分隔、小写）是否位于任一前缀之下。"""
    p = str(path).replace("\\", "/").rstrip("/").lower()
    return any(p == pre or p.startswith(pre + "/") for pre in prefixes)


def scan_all(session: Session, roots: list[Path]) -> ScanStats:
    """依次扫描多个根目录，汇总统计。"""
    total = ScanStats()
    for root in roots:
        total.merge(scan(session, root))
    return total


def add_root(session: Session, root: Path) -> ScanStats:
    """注册并扫描单个根目录（已去重）。"""
    return scan(session, root)


def unlink_root(session: Session, root: Path) -> int:
    """移除根目录：软删其下图片并删除其目录节点，返回移除的图片数。"""
    root = Path(root).resolve()
    # 统一为 / 分隔符，兼容 Windows 反斜杠路径
    prefix = str(root).replace("\\", "/")

    def _under(p: str) -> bool:
        n = str(p).replace("\\", "/")
        return n == prefix or n.startswith(prefix + "/")

    removed = 0
    for im in session.exec(
        select(ImageAsset).where(ImageAsset.is_deleted == 0)
    ).all():
        if _under(im.abs_path):
            im.is_deleted = 1
            removed += 1
    for f in session.exec(select(Folder)).all():
        if _under(f.path):
            session.delete(f)
    session.commit()
    return removed


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
    """扫描目录并建立 Folder 树，返回 {绝对目录路径: folder_id}。"""
    root = Path(root).resolve()
    mapping: dict[str, int] = {}
    for f in session.exec(select(Folder)).all():
        mapping[f.path] = f.id
    for dirpath, dirnames, _ in os.walk(root):
        abs_dir = str(Path(dirpath).resolve())
        if abs_dir in mapping:
            continue
        parent_dir = str(Path(dirpath).parent.resolve())
        parent_id = mapping.get(parent_dir)
        f = Folder(name=Path(dirpath).name or root.name, path=abs_dir, parent_id=parent_id)
        session.add(f)
        session.flush()
        mapping[abs_dir] = f.id
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

    # 注册在 root 之下的嵌套根目录：其子树由嵌套根自己扫描，父根跳过
    nested = _nested_root_prefixes(session, root)
    folder_ids = _ensure_folders(session, root)
    seen_paths: set[str] = set()

    for dirpath, dirnames, files in os.walk(root):
        # 跳过隐藏目录
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in files:
            if Path(name).suffix.lower() not in IMAGE_EXTS:
                continue
            full = Path(dirpath) / name
            if nested and _under_prefix(full, nested):
                continue  # 属于嵌套根目录，由嵌套根扫描
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

            try:
                if existing is None and dup is None:
                    image = ImageAsset(
                        folder_id=folder_ids.get(str(Path(full).parent)),
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
            except IntegrityError:
                # 并发扫描（watcher / 后台扫描同时进行）导致另一事务刚插入了同 file_path：
                # 回滚本次写入，改按“更新”重查并更新该行，避免 UNIQUE 冲突中断整个扫描。
                session.rollback()
                row = session.exec(
                    select(ImageAsset).where(ImageAsset.file_path == rel_norm)
                ).first()
                if row is not None:
                    row.file_name = full.name
                    row.abs_path = str(full)
                    row.width = result.width
                    row.height = result.height
                    row.file_size = size
                    row.file_mtime = mtime
                    row.thumb_ok = thumb_ok
                    row.sha256 = sha
                    row.is_deleted = 0
                    if result.prompt_graph or result.workflow:
                        meta_service.ingest(session, row, result)
                        stats.parsed += 1
                    session.commit()
                    stats.updated += 1
                else:
                    stats.errors.append(f"并发冲突: {rel_norm}")

    # 软删：库中在根内但本次未扫描到的
    root_prefix = str(root.resolve()).rstrip("/")
    for im in session.exec(
        select(ImageAsset).where(
            ImageAsset.is_deleted == 0, ImageAsset.abs_path.like(f"{root_prefix}%")
        )
    ).all():
        if im.file_path not in seen_paths:
            if nested and _under_prefix(im.abs_path, nested):
                continue  # 属于嵌套根目录，不由父根软删
            im.is_deleted = 1
            stats.removed += 1
    session.commit()
    return stats