"""ComfyUI 环境下自动安装缺失依赖（解压即用、无感启动）。

ComfyUI 0.33+ 不再自动安装 custom node 的 requirements.txt；依赖缺失时
路由注册失败会导致图库 tab 白屏（见 __init__._register_routes 的告警）。
本模块在插件加载时检测缺失依赖，用当前解释器（即 ComfyUI venv 的
python）自动 pip 安装：

- 幂等：无缺失依赖时零开销直接返回，重启/多实例不会重复安装；
- 健壮：优先清华镜像（大陆网络），失败自动回退默认 PyPI 源；
- 不阻塞：任何异常仅告警不抛出，绝不中断 ComfyUI 正常加载。
"""
import importlib.util
import logging
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("artmirror.deps")

# pip 包名 → import 模块名 特例（其余按 '-' → '_' 规则转换）
_MODULE_ALIASES = {
    "pillow": "PIL",
    "python-multipart": "multipart",
}

_INSTALL_TIMEOUT = 600  # 秒；首次全量安装（fastapi/sqlmodel 等）可能较慢
_PIP_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def _pkg_to_module(pkg: str) -> str:
    """pip 包名 → 可被 importlib 检测的模块名。"""
    base = pkg.split("[")[0].split(">=")[0].split("==")[0].strip()
    return _MODULE_ALIASES.get(base, base.replace("-", "_"))


def parse_requirements(req_path: Path) -> list[str]:
    """解析 requirements.txt 的包名列表（忽略注释/空行/索引/URL 行）。"""
    names: list[str] = []
    for raw in req_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-", "--")) or "://" in line:
            continue
        name = line.split()[0].split(">=")[0].split("==")[0].split("[")[0].strip()
        if name:
            names.append(name)
    return names


def missing_deps(req_path: Path) -> list[str]:
    """返回 requirements.txt 中当前环境未安装的包名。"""
    return [p for p in parse_requirements(req_path)
            if importlib.util.find_spec(_pkg_to_module(p)) is None]


def _run_pip(args: list[str]) -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--disable-pip-version-check", *args],
            capture_output=True, text=True, timeout=_INSTALL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.error("依赖自动安装超时（>%ss）", _INSTALL_TIMEOUT)
        return False
    except Exception as exc:  # noqa: BLE001
        log.error("依赖自动安装异常: %s", exc)
        return False
    if result.returncode != 0:
        log.warning("pip 安装失败：%s", (result.stderr or result.stdout)[-1500:])
        return False
    return True


def ensure(req_path: Path | None = None) -> None:
    """确保 requirements.txt 依赖已安装（幂等，可安全重复调用）。"""
    req_path = req_path or Path(__file__).resolve().parent.parent / "requirements.txt"
    if not req_path.is_file():
        return
    missing = missing_deps(req_path)
    if not missing:
        return
    log.warning("检测到缺失依赖 %s，正在自动安装（优先清华镜像，首次约需数十秒）…", missing)
    if _run_pip(["install", "-r", str(req_path), "-i", _PIP_MIRROR]):
        log.info("依赖自动安装完成（清华镜像）：%s", missing)
        return
    log.warning("清华镜像安装失败，回退默认 PyPI 源重试…")
    if _run_pip(["install", "-r", str(req_path)]):
        log.info("依赖自动安装完成（默认源）：%s", missing)
    else:
        log.error("依赖自动安装失败，图库 tab 可能无法使用。"
                  "请手动执行: %s -m pip install -r %s",
                  sys.executable, req_path)
