"""默认扫描根：空库时补 ComfyUI 输出目录。"""
import tempfile
from pathlib import Path

import pytest

import artmirror_embed
import comfy_paths


@pytest.fixture(autouse=True)
def _reset_inject():
    """每个用例后复位注入状态，消除与 comfy_paths 测试的顺序依赖。"""
    yield
    comfy_paths.set_paths(None, None)


def _setup(td):
    """注入路径 + 配置 settings + 重建引擎绑定 + 建表，返回数据库模块。"""
    td = Path(td)
    user = td / "user"; out = td / "out"; out.mkdir()
    comfy_paths.set_paths(str(user), str(out))

    from artmirror.config import settings
    settings.configure(
        data_dir=artmirror_embed.resolve_data_dir(),
        frontend_dir=artmirror_embed.resolve_frontend_dir(),
    )
    settings.ensure_dirs()

    from artmirror import database as db
    db.reset_engine()
    db.init_db()
    return db


def test_default_scan_root_added():
    with tempfile.TemporaryDirectory() as td:
        db = _setup(td)
        out = Path(td) / "out"

        from artmirror.services import scanner
        with next(db.get_session()) as session:
            assert list(scanner.get_scan_roots(session)) == []

        artmirror_embed.ensure_default_scan_root()

        with next(db.get_session()) as session:
            roots = list(scanner.get_scan_roots(session))
            assert len(roots) == 1
            assert Path(roots[0]).resolve() == out.resolve()


def test_default_scan_root_keeps_existing():
    """已有扫描根时 ensure_default_scan_root 不追加。"""
    with tempfile.TemporaryDirectory() as td:
        db = _setup(td)
        existing = Path(td) / "existing"; existing.mkdir()

        from artmirror.services import scanner
        with next(db.get_session()) as session:
            scanner.save_scan_roots(session, [str(existing)])

        artmirror_embed.ensure_default_scan_root()

        with next(db.get_session()) as session:
            roots = list(scanner.get_scan_roots(session))
            assert len(roots) == 1
            assert Path(roots[0]).resolve() == existing.resolve()


def test_default_scan_root_skips_missing_output():
    """输出目录不存在时 ensure_default_scan_root 跳过（根仍为空）。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        comfy_paths.set_paths(str(td / "user"), str(td / "missing_out"))  # out 不存在

        from artmirror.config import settings
        settings.configure(
            data_dir=artmirror_embed.resolve_data_dir(),
            frontend_dir=artmirror_embed.resolve_frontend_dir(),
        )
        settings.ensure_dirs()

        from artmirror import database as db
        db.reset_engine()
        db.init_db()

        artmirror_embed.ensure_default_scan_root()

        from artmirror.services import scanner
        with next(db.get_session()) as session:
            assert list(scanner.get_scan_roots(session)) == []
