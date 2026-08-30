"""把 ArtMirror 主仓库 frontend/ 同步为插件内 static/。"""
import shutil
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent
REPO = PLUGIN.parent
SRC = REPO / "frontend"
DST = PLUGIN / "static"

_IGNORE = shutil.ignore_patterns("__pycache__")


def main() -> int:
    if not SRC.is_dir():
        print(f"未找到 {SRC}")
        return 1
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST, ignore=_IGNORE)
    print(f"已同步 {SRC} -> {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
