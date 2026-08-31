"""从真源生成自包含 ComfyUI 插件产物（发布用，替代旧 sync 脚本）。

旧方案靠 sync_*.py 在工作区维护 artmirror_app/ 与 static/ 两份副本；
新架构中插件端是薄启动器，直接复用真源 src/artmirror + frontend/，
发布时才通过本脚本生成自包含产物（可拷贝进 ComfyUI custom_nodes）。

用法：
    python scripts/build_plugin.py [目标目录]
默认输出：build/ComfyUI-ArtMirror/（已被 .gitignore 忽略，属构建产物）
"""
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "comfyui-plugin"
SRC = REPO / "src" / "artmirror"
FRONTEND = REPO / "frontend"

# 插件骨架中不随产物分发的部分
_SKIP = {"tests", "sync_all.py", "sync_backend.py", "sync_frontend.py"}
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "build" / "ComfyUI-ArtMirror"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    # 1. 插件骨架（启动器 + 代理 + ComfyUI 集成，排除测试与旧同步脚本）
    for item in PLUGIN.iterdir():
        if item.name in _SKIP:
            continue
        dst = target / item.name
        if item.is_dir():
            shutil.copytree(item, dst, ignore=_IGNORE)
        else:
            shutil.copy2(item, dst)

    # 2. 真源核心包 + 前端（产物内自包含，嵌入环境无需安装 artmirror 包）
    shutil.copytree(SRC, target / "artmirror", ignore=_IGNORE)
    shutil.copytree(FRONTEND, target / "static", ignore=_IGNORE)

    print(f"插件产物已生成: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
