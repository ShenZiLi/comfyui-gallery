"""把 ArtMirror 主仓库 backend/app 同步为插件内 artmirror_app/。

用法：python sync_backend.py（需在插件目录或仓库根执行，脚本自动定位）。
"""
import shutil
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent
REPO = PLUGIN.parent
SRC = REPO / "backend" / "app"
DST = PLUGIN / "artmirror_app"

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def main() -> int:
    if not SRC.is_dir():
        print(f"未找到 {SRC}")
        return 1
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST, ignore=_IGNORE)
    # 标识这是同步副本
    (DST / "__init__.py").write_text(
        '"""ArtMirror 后端（由 sync_backend.py 从主仓库同步，勿手改）。"""\n',
        encoding="utf-8",
    )
    print(f"已同步 {SRC} -> {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
