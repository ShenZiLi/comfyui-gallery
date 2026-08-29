"""config.py 冻结态（PyInstaller）路径计算测试。"""
import sys
from pathlib import Path

import app.config as config_mod


def _fake_module_root():
    return Path("C:/proj")


def test_dev_paths(monkeypatch):
    """开发态：数据目录=项目根/data，前端=项目根/frontend。"""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(config_mod, "_module_root", _fake_module_root)
    assert config_mod._app_base_dir() == Path("C:/proj")
    assert config_mod._frontend_base_dir() == Path("C:/proj/frontend")


def test_frozen_paths(monkeypatch):
    """打包态：数据目录=exe 所在目录/data，前端=_MEIPASS/frontend。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:/exe/画镜ArtMirror.exe", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "C:/tmp/am_meipass", raising=False)
    assert config_mod._app_base_dir() == Path("C:/exe")
    assert config_mod._frontend_base_dir() == Path("C:/tmp/am_meipass/frontend")
