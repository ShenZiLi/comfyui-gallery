"""一键同步 Web 端真源到插件副本，或校验副本与真源逐文件一致。

用法（在仓库根执行）：
    python comfyui-plugin/sync_all.py          # 同步：backend/app -> artmirror_app/，frontend/ -> static/
    python comfyui-plugin/sync_all.py --check  # 仅校验；副本漂移时输出差异并退出码非 0

改主仓库 backend/app 或 frontend/ 后必须重跑同步，插件副本才会更新。
"""
import argparse
import hashlib
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent
REPO = PLUGIN.parent

# (真源, 副本目标)
PAIRS = [
    (REPO / "backend" / "app", PLUGIN / "artmirror_app"),
    (REPO / "frontend", PLUGIN / "static"),
]

# 后端副本的 __init__.py 是同步标识（内容不同于真源），不逐字比较
BACKEND_SKIP = {"__init__.py"}
# 前端副本生成的标识文件，真源不存在，不计入漂移
DST_ONLY_SKIP = {".am-synced"}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _files(base: Path) -> dict[str, Path]:
    """目录内 相对路径 -> 文件（跳过 __pycache__）。"""
    out = {}
    for p in base.rglob("*"):
        if p.is_dir() or "__pycache__" in p.parts:
            continue
        rel = str(p.relative_to(base)).replace("\\", "/")
        if rel in DST_ONLY_SKIP:
            continue
        out[rel] = p
    return out


def diff(src: Path, dst: Path) -> dict[str, list[str]]:
    """返回 {only_src, only_dst, differs} 三组相对路径列表。"""
    sf, df = _files(src), _files(dst)
    only_src = sorted(set(sf) - set(df))
    only_dst = sorted(set(df) - set(sf))
    differs = []
    for rel in sorted(set(sf) & set(df)):
        if rel in BACKEND_SKIP:
            continue
        if _sha(sf[rel]) != _sha(df[rel]):
            differs.append(rel)
    return {"only_src": only_src, "only_dst": only_dst, "differs": differs}


def check() -> list[tuple[Path, Path, dict[str, list[str]]]]:
    """校验所有副本，返回存在差异的条目；空列表 = 全部一致。"""
    issues = []
    for src, dst in PAIRS:
        d = diff(src, dst)
        if any(d.values()):
            issues.append((src, dst, d))
    return issues


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="仅校验副本与真源逐文件一致，不写副本")
    args = ap.parse_args(argv)

    if args.check:
        issues = check()
        if not issues:
            print("副本与真源一致 ✓")
            return 0
        for src, dst, d in issues:
            print(f"副本漂移: {dst.relative_to(PLUGIN)}  ←  {src.relative_to(REPO)}")
            for key, label in (
                ("only_src", "仅真源有"),
                ("only_dst", "仅副本有"),
                ("differs", "内容不一致"),
            ):
                if d[key]:
                    print(f"  {label}: {d[key]}")
        print("提示: 运行 python comfyui-plugin/sync_all.py 重新同步。")
        return 1

    # 同步：复用两个同步脚本
    from sync_backend import main as sync_backend_main
    from sync_frontend import main as sync_frontend_main

    rc = sync_backend_main()
    rc |= sync_frontend_main()
    if rc == 0:
        print("同步完成: backend/app -> artmirror_app/，frontend/ -> static/")
    return rc


if __name__ == "__main__":
    sys.exit(main())
