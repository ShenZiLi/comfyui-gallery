"""comfyui/install_deps 自动依赖安装逻辑测试（纯函数，不触发真实 pip 安装）。"""
from pathlib import Path

from comfyui import install_deps


def test_pkg_to_module():
    """pip 包名 → import 模块名 映射（含 extra/版本/连字符/特例）。"""
    cases = {
        "uvicorn": "uvicorn",
        "uvicorn[standard]": "uvicorn",
        "fastapi>=0.115": "fastapi",
        "sqlmodel==0.0.42": "sqlmodel",
        "pydantic-settings>=2.6": "pydantic_settings",
        "pillow>=11.0": "PIL",
        "python-multipart>=0.0.9": "multipart",
        "send2trash>=1.8": "send2trash",
    }
    for pkg, expected in cases.items():
        assert install_deps._pkg_to_module(pkg) == expected, pkg


def test_parse_requirements(tmp_path: Path):
    """忽略注释/空行/索引行/URL 行，仅保留包名。"""
    req = tmp_path / "requirements.txt"
    req.write_text(
        "# 注释\n"
        "\n"
        "-r other.txt\n"
        "--index-url https://example.com/simple\n"
        "fastapi>=0.115\n"
        "uvicorn[standard]>=0.32\n"
        "pillow>=11.0\n",
        encoding="utf-8",
    )
    assert install_deps.parse_requirements(req) == ["fastapi", "uvicorn", "pillow"]


def test_missing_deps_detects_absent(tmp_path: Path):
    """存在模块 → 不缺失；不存在包 → 缺失。"""
    req = tmp_path / "requirements.txt"
    req.write_text(
        "httpx>=0.27\n"  # 当前环境必有
        "this-package-does-not-exist-artmirror-xyz\n",
        encoding="utf-8",
    )
    missing = install_deps.missing_deps(req)
    assert "this-package-does-not-exist-artmirror-xyz" in missing
    assert "httpx" not in missing


def test_ensure_no_req_file_is_safe(tmp_path: Path):
    """requirements.txt 不存在时安全返回，不抛异常。"""
    install_deps.ensure(tmp_path / "nonexistent-requirements.txt")


def test_ensure_idempotent_when_all_installed(tmp_path: Path, monkeypatch):
    """无缺失依赖时零开销返回，绝不触发 pip。"""
    req = tmp_path / "requirements.txt"
    req.write_text("httpx>=0.27\n", encoding="utf-8")  # 当前环境必有

    called = []
    monkeypatch.setattr(install_deps, "_run_pip", lambda *a: called.append(a) or True)
    install_deps.ensure(req)
    assert called == []
