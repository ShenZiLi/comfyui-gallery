"""把 ArtMirror 主仓库 frontend/ 同步为插件内 static/。"""
import shutil
import sys
from datetime import datetime
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
    # 同步标识：便于识别这是生成物副本（勿手改）
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    (DST / ".am-synced").write_text(
        "ArtMirror 前端同步副本\n"
        f"来源: {SRC}\n"
        f"同步时间: {stamp}\n"
        "勿手改此目录；改动主仓库 frontend/ 后重跑同步（sync_all.py）。\n",
        encoding="utf-8",
    )
    print(f"已同步 {SRC} -> {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
