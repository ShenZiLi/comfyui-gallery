"""目录浏览器路由。

供前端“服务端驱动”的文件夹选择弹窗使用：列出本机可用根与指定目录的子目录，
从而拿到真实绝对路径，用于链接本地图片并实时同步。
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/fs", tags=["fs"])


def _abs(path: str | None) -> Path:
    target = Path(path).expanduser() if path else Path.home()
    return target.resolve()


@router.get("/roots")
def fs_roots() -> list[dict]:
    """返回可选择起始的目录（home、常见卷、根）。"""
    home = Path.home().resolve()
    candidates = [home]
    volumes = Path("/Volumes")
    if volumes.is_dir():
        for v in volumes.iterdir():
            if v.is_dir():
                candidates.append(v)
    if home != Path("/"):
        candidates.append(Path("/"))

    seen: set[str] = set()
    out: list[dict] = []
    for r in candidates:
        key = str(r.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": r.name or str(r), "path": key, "isDir": True})
    return out


@router.get("/list")
def fs_list(path: str = "") -> dict:
    """列出指定目录的直接子目录。"""
    target = _abs(path)
    if not target.is_dir():
        raise HTTPException(400, "目录不存在")
    parent = str(target.parent) if target.parent != target else ""
    items: list[dict] = []
    try:
        children = sorted(
            target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
        )
    except PermissionError:
        raise HTTPException(403, "无权限访问该目录")  # noqa: B904
    for child in children:
        if child.name.startswith(".") or not child.is_dir():
            continue
        items.append({"name": child.name, "path": str(child.resolve()), "isDir": True})
    return {"path": str(target), "parent": parent, "items": items}