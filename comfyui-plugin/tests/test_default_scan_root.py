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

    from artmirror_app.config import settings
    artmirror_embed._configure(settings)
    settings.ensure_dirs()

    from artmirror_app import database as db
    artmirror_embed._rebind_engine(settings)
    db.init_db()
    return db


def _ensure_default_scan_root(db):
    """调用 ensure_default_scan_root（内部会重建引擎），并 dispose 被替换的旧引擎。

    ensure_default_scan_root 自洽地 _rebind_engine，替换后的新引擎由调用方
    在用例收尾 dispose；这里补 dispose 旧引擎，避免其连接池占用 SQLite 句柄，
    导致 Windows 临时目录清理失败。
    """
    prev = db.engine
    artmirror_embed.ensure_default_scan_root()
    prev.dispose()


def test_default_scan_root_added():
    with tempfile.TemporaryDirectory() as td:
        db = _setup(td)
        out = Path(td) / "out"

        from artmirror_app.services import scanner
        with next(db.get_session()) as session:
            assert list(scanner.get_scan_roots(session)) == []

        _ensure_default_scan_root(db)

        with next(db.get_session()) as session:
            roots = list(scanner.get_scan_roots(session))
            assert len(roots) == 1
            assert Path(roots[0]).resolve() == out.resolve()

        db.engine.dispose()


def test_default_scan_root_keeps_existing():
    """已有扫描根时 ensure_default_scan_root 不追加。"""
    with tempfile.TemporaryDirectory() as td:
        db = _setup(td)
        existing = Path(td) / "existing"; existing.mkdir()

        from artmirror_app.services import scanner
        with next(db.get_session()) as session:
            scanner.save_scan_roots(session, [str(existing)])

        _ensure_default_scan_root(db)

        with next(db.get_session()) as session:
            roots = list(scanner.get_scan_roots(session))
            assert len(roots) == 1
            assert Path(roots[0]).resolve() == existing.resolve()

        db.engine.dispose()


def test_default_scan_root_skips_missing_output():
    """输出目录不存在时 ensure_default_scan_root 跳过（根仍为空）。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        comfy_paths.set_paths(str(td / "user"), str(td / "missing_out"))  # out 不存在

        from artmirror_app.config import settings
        artmirror_embed._configure(settings)
        settings.ensure_dirs()

        from artmirror_app import database as db
        artmirror_embed._rebind_engine(settings)
        db.init_db()

        _ensure_default_scan_root(db)

        from artmirror_app.services import scanner
        with next(db.get_session()) as session:
            assert list(scanner.get_scan_roots(session)) == []

        db.engine.dispose()
