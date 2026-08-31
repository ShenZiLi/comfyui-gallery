"""从真源同步 ComfyUI 插件产物（插件端为主，web 端为辅）。

设计：插件端「解压即用」——comfyui-plugin/ 自带核心产物并随 git 入库，
用户 clone/下载后直接拷到 custom_nodes 即可，无需先构建。
依赖由 ComfyUI 启动时按插件内 requirements.txt 自动安装（标准机制）。

两种模式：
  python scripts/build_plugin.py                 # inplace：同步核心产物到 comfyui-plugin/（日常开发后提交）
  python scripts/build_plugin.py --out 目录       # 发布：生成完整自包含插件包（骨架 + 产物，可选 --bundle-deps）
  python scripts/build_plugin.py --out 目录 --bundle-deps [--python 3.12]   # 离线包：_deps/ 一并打包
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "comfyui-plugin"
SRC = REPO / "src" / "artmirror"
FRONTEND = REPO / "frontend"
REQUIREMENTS = REPO / "requirements.txt"

# 发布包中不随产物分发的部分
_SKIP = {"tests"}
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "_deps")


def _sync_core(target: Path) -> None:
    """把真源核心包与前端同步为插件内产物（artmirror/ + static/）。"""
    for src, dst in ((SRC, target / "artmirror"), (FRONTEND, target / "static")):
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=_IGNORE)


def _vendor_dependencies(target: Path, python_spec: str | None) -> None:
    """vendoring 运行时依赖到产物 _deps/（离线包用）。

    _deps 含编译型包（pydantic-core 等），必须与 ComfyUI 的 Python 版本匹配，
    由 --python 指定（默认当前解释器）。
    """
    deps = target / "_deps"
    deps.mkdir(exist_ok=True)
    print("vendoring 依赖到 _deps/（首次较慢，需联网）…")
    cmd = ["uv", "pip", "install", "--target", str(deps), "-r", str(REQUIREMENTS)]
    if python_spec:
        cmd += ["--python", python_spec]
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="从真源生成 ComfyUI 插件产物")
    parser.add_argument(
        "--out", default=None,
        help="发布模式：输出完整自包含插件包到该目录",
    )
    parser.add_argument(
        "--bundle-deps", action="store_true",
        help="发布模式下同时 vendoring 依赖到 _deps/（离线解压即用，包体 ~47M）",
    )
    parser.add_argument(
        "--python", default=None,
        help="目标 ComfyUI 环境的 Python（如 3.12 或解释器路径），用于 _deps vendoring",
    )
    args = parser.parse_args()

    if args.out:
        # 发布模式：完整自包含插件包
        target = Path(args.out)
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for item in PLUGIN.iterdir():
            if item.name in _SKIP:
                continue
            dst = target / item.name
            if item.is_dir():
                shutil.copytree(item, dst, ignore=_IGNORE)
            else:
                shutil.copy2(item, dst)
        # 产物已随插件目录入库，直接继承；再同步一次确保与真源一致
        _sync_core(target)
        if args.bundle_deps:
            _vendor_dependencies(target, args.python)
        print(f"插件发布包已生成: {target}")
    else:
        # inplace 模式：同步核心产物到插件目录（日常开发后提交）
        _sync_core(PLUGIN)
        print(f"已同步核心产物到 {PLUGIN}/（artmirror/ + static/，可提交）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
