"""sync_all.py 一键同步与一致性校验验证。"""
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
REPO = PLUGIN.parent

BACKEND_DST = PLUGIN / "artmirror_app"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PLUGIN / "sync_all.py"), *args],
        capture_output=True, text=True, cwd=str(REPO),
    )


def test_sync_all_check_passes_after_sync():
    """同步后 --check 应通过（退出码 0）。"""
    assert _run().returncode == 0
    check = _run("--check")
    assert check.returncode == 0, check.stdout + check.stderr


def test_sync_all_check_detects_drift():
    """副本被手改后 --check 应失败（退出码非 0），且不写回副本。"""
    assert _run().returncode == 0
    target = BACKEND_DST / "common.py"
    original = target.read_bytes()
    drifted = original + b"\n# drift\n"
    target.write_bytes(drifted)
    try:
        check = _run("--check")
        assert check.returncode != 0, check.stdout + check.stderr
        assert "common.py" in check.stdout, check.stdout
        # --check 只读校验，不写回副本
        assert target.read_bytes() == drifted
    finally:
        target.write_bytes(original)
