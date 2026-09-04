"""图片 PNG 无损压缩路由（单张 + 批量）。

compress_mode=overwrite 时在原路径覆盖；=new（默认）时写入导入目录并注册为扫描根。
压缩后若不减小则跳过不写。
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlmodel import Session, select

from ..config import settings
from ..database import get_engine, get_session
from ..models import ImageAsset, Setting
from ..services import compress as compress_svc, scanner, watcher
from .images import _move_to_trash

router = APIRouter(prefix="/api/images", tags=["compress"])


def _get(session: Session, key: str) -> str | None:
    row = session.exec(select(Setting).where(Setting.key == key)).first()
    return row.value if row and row.value else None


def _import_dir(session: Session) -> Path:
    """导入保存目录：优先设置页配置项 import_dir，未配则默认 data/import。"""
    cfg = _get(session, "import_dir")
    if cfg:
        return Path(cfg)
    return Path(settings.data_dir) / "import"


def _background_scan(root: Path) -> None:
    """后台扫描目录，有变动则递增同步版本号（独立线程，异常不抛出）。"""

    def _run():
        try:
            from sqlmodel import Session as _S

            with _S(get_engine()) as session:
                stats = scanner.scan(session, root)
                if stats.new or stats.updated or stats.removed:
                    watcher.bump()
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_run, daemon=True).start()


def _unique_path(root: Path, stem: str) -> Path:
    target = root / f"{stem}_compressed.png"
    i = 1
    while target.exists():
        target = root / f"{stem}_compressed-{i}.png"
        i += 1
    return target


def _compress_one(session: Session, im: ImageAsset) -> dict:
    """压缩单张图片（可被后端浏览器直接从文件落盘复用；返回结果 dict）。"""
    mode = (_get(session, "compress_mode") or "new").strip()
    keep = (_get(session, "compress_keep_meta") or "true") != "false"

    src = Path(im.abs_path)
    if src.suffix.lower() != ".png":
        raise HTTPException(400, "仅支持 PNG 格式")
    if not src.is_file():
        raise HTTPException(404, "源文件不存在")

    old = src.stat().st_size
    data = compress_svc.compress_png(src, keep_meta=keep)
    if len(data) >= old:
        return {
            "id": im.id, "original": old, "compressed": len(data),
            "saved": False, "new_file": None, "reason": "压缩后反而更大，已跳过",
        }

    if mode == "overwrite":
        # 先写临时文件确保能落盘 → 再备份原图到废纸篓 → 最后同卷原子替换，
        # 避免写入失败导致原图丢失（数据丢失窗口）。
        tmp = src.with_name(src.stem + ".comp.tmp")
        try:
            tmp.write_bytes(data)
            _move_to_trash(src)
            os.replace(tmp, src)
        except Exception:  # noqa: BLE001
            # 任一环节失败：尽量保证原图完好（仅当原路径已丢失且临时文件在时回填）
            if tmp.exists() and not src.exists():
                try:
                    os.replace(tmp, src)
                except Exception:  # noqa: BLE001
                    pass
            raise
        watcher.bump()
        return {
            "id": im.id, "original": old, "compressed": len(data),
            "saved": True, "new_file": str(src), "reason": "",
        }

    # 默认 new：写入导入目录并注册为扫描根，后台扫描使其重新入库
    import_dir = _import_dir(session)
    import_dir.mkdir(parents=True, exist_ok=True)
    roots = scanner.get_scan_roots(session)
    key = str(import_dir.resolve())
    if key not in {str(r.resolve()) for r in roots}:
        scanner.save_scan_roots(session, [str(r) for r in roots] + [key])
    new_path = _unique_path(import_dir, src.stem)
    new_path.write_bytes(data)
    _background_scan(import_dir)
    return {
        "id": im.id, "original": old, "compressed": len(data),
        "saved": True, "new_file": str(new_path), "reason": "",
    }


@router.post("/{image_id}/compress")
def compress_image(image_id: int, session: Session = Depends(get_session)):
    """压缩单张 PNG。"""
    im = session.get(ImageAsset, image_id)
    if im is None or im.is_deleted:
        raise HTTPException(404, "image not found")
    return _compress_one(session, im)


@router.post("/batch-compress")
def batch_compress(ids: list[int] = Body(...), session: Session = Depends(get_session)):
    """批量压缩 PNG：逐张独立处理，失败条目仅标记 saved=False 不中断整体。"""
    results = []
    saved_count = 0
    for image_id in ids:
        im = session.get(ImageAsset, image_id)
        if im is None or im.is_deleted:
            results.append({
                "id": image_id, "original": 0, "compressed": 0,
                "saved": False, "new_file": None, "reason": "图片不存在",
            })
            continue
        try:
            res = _compress_one(session, im)
        except HTTPException as exc:
            res = {
                "id": image_id, "original": 0, "compressed": 0,
                "saved": False, "new_file": None, "reason": exc.detail,
            }
        except Exception as exc:  # noqa: BLE001
            res = {
                "id": image_id, "original": 0, "compressed": 0,
                "saved": False, "new_file": None, "reason": str(exc),
            }
        if res["saved"]:
            saved_count += 1
        results.append(res)
    return {"results": results, "total": len(ids), "saved_count": saved_count}