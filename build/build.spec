# -*- mode: python ; coding: utf-8 -*-
"""画镜 ArtMirror 单文件 exe 打包配置。在 build/ 下由 build.ps1 调用。"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent  # 项目根（build.spec 位于 build/）
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ICON = ROOT / "build" / "icon.ico"

a = Analysis(
    [str(BACKEND / "run.py")],
    pathex=[str(BACKEND)],
    binaries=[],
    datas=[(str(FRONTEND), "frontend")],
    hiddenimports=[
        "sqlmodel", "pydantic", "multipart", "send2trash", "send2trash.win",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# 兜底收集 uvicorn 全量子模块（动态导入易遗漏）
# collect_all 返回 hook 风格 2 元组 (source, target)，需转为 TOC 3 元组 (target, source, typecode)；
# 并过滤目录条目（collect_data_files 可能误收 .dist-info 目录，打包时无法作为文件打开）。
for pkg in ("uvicorn", "fastapi", "starlette"):
    _d, _b, _h = collect_all(pkg)
    a.datas += [(dest, src, "DATA") for src, dest in _d if Path(src).is_file()]
    a.binaries += [(dest, src, "BINARY") for src, dest in _b if Path(src).is_file()]
    a.hiddenimports += _h

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="画镜ArtMirror",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,            # 无窗口静默运行
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
)
