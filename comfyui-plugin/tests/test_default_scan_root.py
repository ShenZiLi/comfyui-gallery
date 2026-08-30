"""默认扫描根：空库时补 ComfyUI 输出目录。"""
import tempfile
from pathlib import Path

import artmirror_embed
import comfy_paths


def test_default_scan_root_added():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        user = td / "user"; out = td / "out"; out.mkdir()
        comfy_paths.set_paths(str(user), str(out))

        from artmirror_app.config import settings
        artmirror_embed._configure(settings)
        settings.ensure_dirs()

        # 空库初始化：生产上由 artmirror_embed.start() 的 startup 事件完成建表，
        # 测试直接调用 embed 时需手动重建引擎绑定 + init_db（否则无 setting 表）；
        # 结束前 dispose 释放 SQLite 句柄，避免 Windows 临时目录清理失败。
        from artmirror_app import database as db
        artmirror_embed._rebind_engine(settings)
        db.init_db()

        from artmirror_app.services import scanner
        with next(db.get_session()) as session:
            assert list(scanner.get_scan_roots(session)) == []

        artmirror_embed.ensure_default_scan_root()

        with next(db.get_session()) as session:
            roots = list(scanner.get_scan_roots(session))
            assert len(roots) == 1
            assert Path(roots[0]).resolve() == out.resolve()

        db.engine.dispose()
