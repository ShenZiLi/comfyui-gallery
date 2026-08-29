"""目录浏览器路由测试。"""
import tempfile
from pathlib import Path

from app.routers import fs


def test_fs_roots():
    roots = fs.fs_roots()
    assert isinstance(roots, list) and roots
    assert all(r["isDir"] for r in roots)
    assert all(Path(r["path"]).is_absolute() for r in roots)


def test_fs_list():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "sub").mkdir()
        (base / "file.txt").write_text("x")
        data = fs.fs_list(str(base))
        assert Path(data["path"]).resolve() == base.resolve()
        assert data["parent"]  # 上级存在
        names = [it["name"] for it in data["items"]]
        assert "sub" in names
        assert "file.txt" not in names  # 仅目录


def test_fs_list_missing():
    try:
        fs.fs_list("/no/such/dir/am_xyz")
    except Exception as exc:  # noqa: BLE001
        assert exc.__class__.__name__ == "HTTPException"