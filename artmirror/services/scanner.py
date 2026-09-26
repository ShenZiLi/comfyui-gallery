"""图片扫描与入库服务。

递归扫描多个配置根目录，按规范化物理路径识别资产，mtime+size 增量更新并缓存缩略图，
并把 ComfyUI meta 解析后落库；对已消失文件做软删除。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image
from sqlmodel import Session, select

from ..config import settings
from ..models import Folder, ImageAsset, Setting, WorkflowMeta
from ..parsers.comfyui_parser import parse_bytes
from ..database import normalize_path_key as normalize_path_key_db
from . import meta_service

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
THUMB_SIZE = (480, 600)


def normalize_path_key(path: str) -> str:
    """规范化物理路径；Windows 路径按大小写不敏感处理。"""
    return normalize_path_key_db(path)


@dataclass
class ScanStats:
    """扫描统计。"""

    new: int = 0
    updated: int = 0
    skipped: int = 0
    removed: int = 0
    parsed: int = 0
    files_total: int = 0
    files_done: int = 0
    current_file: str = ""
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "ScanStats") -> "ScanStats":
        self.new += other.new
        self.updated += other.updated
        self.skipped += other.skipped
        self.removed += other.removed
        self.parsed += other.parsed
        self.files_total += other.files_total
        self.files_done += other.files_done
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


def scan(
    session: Session,
    root: Path,
    *,
    reparse_missing: bool = True,
    progress: Callable[[ScanStats], None] | None = None,
) -> ScanStats:
    """执行一次扫描；先枚举并 stat 一次，再处理图片并按批次提交。"""
    stats = ScanStats()
    root = Path(root).resolve()
    if not root.is_dir():
        stats.errors.append(f"目录不存在: {root}")
        return stats
    settings.ensure_dirs()
    nested = _nested_root_prefixes(session, root)
    folder_rows = session.exec(select(Folder)).all()
    folder_ids = {f.path: f.id for f in folder_rows}
    manifest: list[tuple[Path, str, str, int, float]] = []
    seen_keys: set[str] = set()

    # One top-down walk builds the folder tree and captures one stat per image.
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and not (nested and _under_prefix(Path(dirpath) / d, nested))
        ]
        abs_dir = str(Path(dirpath).resolve())
        if abs_dir not in folder_ids:
            parent_dir = str(Path(dirpath).parent.resolve())
            folder = Folder(
                name=Path(dirpath).name or root.name,
                path=abs_dir,
                parent_id=folder_ids.get(parent_dir),
            )
            session.add(folder)
            session.flush()
            folder_ids[abs_dir] = folder.id
        for name in files:
            if Path(name).suffix.lower() not in IMAGE_EXTS:
                continue
            full = Path(dirpath) / name
            if nested and _under_prefix(full, nested):
                continue
            rel_path = os.path.relpath(full, root).replace(os.sep, "/")
            key = normalize_path_key(str(full))
            seen_keys.add(key)
            stats.files_total += 1
            try:
                st = full.stat()
            except OSError as exc:
                stats.errors.append(f"{full}: {exc}")
                continue
            manifest.append((full, rel_path, key, st.st_size, st.st_mtime))
    stats.files_done = stats.files_total - len(manifest)
    session.commit()
    if progress:
        progress(stats)

    # Preload image rows and small metadata fields once, avoiding per-file selects.
    all_images = session.exec(select(ImageAsset)).all()
    images_by_key = {
        im.path_key: im for im in all_images if im.path_key and not im.is_deleted
    }
    deleted_by_key: dict[str, ImageAsset] = {}
    for image in all_images:
        if image.path_key and image.is_deleted:
            prev = deleted_by_key.get(image.path_key)
            if prev is None or (image.update_time, image.id) > (prev.update_time, prev.id):
                deleted_by_key[image.path_key] = image
    metas = {
        row.image_id: row
        for row in session.exec(select(WorkflowMeta)).all()
    }
    pending = 0

    for full, rel_path, key, size, mtime in manifest:
        image = images_by_key.get(key)
        if image is None:
            image = deleted_by_key.get(key)
        meta = metas.get(image.id) if image else None
        needs_reparse = bool(
            reparse_missing
            and meta
            and not (meta.prompt or "").strip()
            and (meta.parser_revision or 0) < meta_service.PARSER_REVISION
        )
        unchanged = bool(
            image
            and image.file_size == size
            and abs((image.file_mtime or 0) - mtime) < 1e-6
        )
        if unchanged and image.is_deleted == 0 and not needs_reparse:
            stats.skipped += 1
        else:
            try:
                data = full.read_bytes()
                sha = _hash_bytes(data)
                result = parse_bytes(data)
                thumb_path = settings.thumbs_dir / f"{sha}.webp"
                if thumb_path.is_file():
                    thumb_ok = 1
                else:
                    try:
                        thumb_path.write_bytes(_make_thumb(data))
                        thumb_ok = 1
                    except Exception:  # noqa: BLE001
                        thumb_ok = 0

                is_new = image is None
                with session.begin_nested():
                    if is_new:
                        image = ImageAsset(
                            folder_id=folder_ids.get(str(full.parent.resolve())),
                            file_name=full.name,
                            file_path=rel_path,
                            abs_path=str(full),
                            path_key=key,
                        )
                        session.add(image)
                    else:
                        image.folder_id = folder_ids.get(str(full.parent.resolve()))
                        image.file_name = full.name
                        image.file_path = rel_path
                        image.abs_path = str(full)
                        image.path_key = key
                        image.is_deleted = 0
                    image.sha256 = sha
                    image.width = result.width
                    image.height = result.height
                    image.file_size = size
                    image.file_mtime = mtime
                    image.thumb_ok = thumb_ok
                    session.flush()
                    if result.prompt_graph or result.workflow:
                        meta_service.ingest(session, image, result)
                        stats.parsed += 1
                    elif meta and needs_reparse:
                        meta.parser_revision = meta_service.PARSER_REVISION
                    session.flush()
                pending += 1
                if is_new:
                    images_by_key[key] = image
                    stats.new += 1
                else:
                    stats.updated += 1
            except Exception as exc:  # noqa: BLE001 — 单图失败不阻断整轮扫描
                stats.errors.append(f"{full}: {exc}")

        stats.files_done += 1
        stats.current_file = str(full)
        if progress:
            progress(stats)
        if pending >= 50:
            session.commit()
            pending = 0

    if pending:
        session.commit()

    root_key = normalize_path_key(str(root)).rstrip("\\/")
    prefix = root_key + ("\\" if "\\" in root_key else "/")
    for image in session.exec(select(ImageAsset).where(ImageAsset.is_deleted == 0)).all():
        image_key = image.path_key or normalize_path_key(image.abs_path)
        if image_key.startswith(prefix) and image_key not in seen_keys:
            if nested and _under_prefix(image.abs_path, nested):
                continue
            image.is_deleted = 1
            stats.removed += 1
    session.commit()
    return stats


def scan_all(
    session: Session,
    roots: list[Path],
    *,
    reparse_missing: bool = True,
    progress: Callable[[Path, ScanStats], None] | None = None,
) -> ScanStats:
    """依次扫描多个根目录，汇总统计。"""
    total = ScanStats()
    for root in roots:
        callback = (lambda stats, root=root: progress(root, stats)) if progress else None
        total.merge(scan(session, root, reparse_missing=reparse_missing, progress=callback))
    return total
