"""把整个仓库打包为可「解压即用」的 ComfyUI 插件 zip。

仓库根即插件包（__init__.py + web/ + requirements.txt），clone 后直接放入
custom_nodes/ArtMirror 即可；本脚本仅为分发给小白用户提供单文件 zip。

用法：
    python scripts/build_plugin.py [输出.zip]
默认输出：build/ArtMirror-comfyui-plugin.zip

排除：开发/运行数据（.git、.venv、data、test_data、docs、tests、构建产物等）。
"""
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 打包时排除的目录与文件（插件运行不需要）
_EXCLUDE_DIRS = {
    ".git", ".idea", ".trae", ".workbuddy", "__pycache__", ".pytest_cache",
    ".venv", "data", "test_data", "build", "docs", "tests", "scripts",
}
_EXCLUDE_FILES = {".DS_Store", "start.ps1", "启动Web端-Win.bat"}


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "build" / "ArtMirror-comfyui-plugin.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(REPO.iterdir()):
            if item.name in _EXCLUDE_DIRS or item.name in _EXCLUDE_FILES:
                continue
            paths = sorted(item.rglob("*")) if item.is_dir() else [item]
            for p in paths:
                if not p.is_file():
                    continue
                if any(part in _EXCLUDE_DIRS or part in _EXCLUDE_FILES for part in p.parts):
                    continue
                if p.name == ".DS_Store":
                    continue
                zf.write(p, p.relative_to(REPO))

    size = out.stat().st_size / 1024 / 1024
    print(f"插件 zip 已生成: {out}（{size:.1f} MB，解压后放入 custom_nodes/ArtMirror 重启即用）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
