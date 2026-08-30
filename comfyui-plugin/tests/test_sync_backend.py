"""后端同步脚本验证：artmirror_app 可导入且含 main.app。"""
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent


def test_artmirror_app_importable():
    """artmirror_app 包存在且可导入 app.main（同步脚本已运行）。"""
    import artmirror_app
    from artmirror_app import main
    assert hasattr(main, "app")


def test_sync_script_updates_copy():
    """重跑同步脚本后 artmirror_app 与 backend/app 文件清单一致。"""
    result = subprocess.run(
        [sys.executable, str(PLUGIN / "sync_backend.py")],
        capture_output=True, text=True, cwd=str(PLUGIN.parent),
    )
    assert result.returncode == 0, result.stderr
    src = set(p.name for p in (PLUGIN.parent / "backend" / "app").rglob("*.py") if "__pycache__" not in str(p))
    dst = set(p.name for p in (PLUGIN / "artmirror_app").rglob("*.py") if "__pycache__" not in str(p))
    assert dst >= src
