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
    """重跑同步脚本后 artmirror_app 与 backend/app 相对路径集合一致且内容同源。"""
    result = subprocess.run(
        [sys.executable, str(PLUGIN / "sync_backend.py")],
        capture_output=True, text=True, cwd=str(PLUGIN.parent),
    )
    assert result.returncode == 0, result.stderr
    src_dir = PLUGIN.parent / "backend" / "app"
    dst_dir = PLUGIN / "artmirror_app"

    def rel_set(base: Path):
        return {
            str(p.relative_to(base))
            for p in base.rglob("*.py")
            if "__pycache__" not in str(p)
        }

    src_rel = rel_set(src_dir)
    dst_rel = rel_set(dst_dir)
    assert dst_rel == src_rel, f"路径集合不一致: 多={sorted(dst_rel - src_rel)} 缺={sorted(src_rel - dst_rel)}"

    import hashlib

    def sha(p: Path):
        return hashlib.sha256(p.read_bytes()).hexdigest()

    # 公共文件内容一致（除 __init__.py 为同步标识外）
    for rel in src_rel:
        if rel == "__init__.py":
            continue
        assert sha(src_dir / rel) == sha(dst_dir / rel), f"内容不一致: {rel}"
