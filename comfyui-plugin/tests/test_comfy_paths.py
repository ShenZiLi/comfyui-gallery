"""ComfyUI 路径适配器测试（可注入，脱离 ComfyUI 运行）。"""
import os

import pytest

import comfy_paths


@pytest.fixture(autouse=True)
def _reset_inject():
    """每个用例后复位注入状态，消除全局状态顺序依赖。"""
    yield
    comfy_paths.set_paths(None, None)


def test_set_paths_override():
    """显式注入路径后，get_user_dir/get_output_dir 返回注入值。"""
    comfy_paths.set_paths("C:/u", "C:/out")
    assert comfy_paths.get_user_dir() == "C:/u"
    assert comfy_paths.get_output_dir() == "C:/out"


def test_fallback_defaults():
    """未注入且无 ComfyUI 时回退到 ~/ComfyUI。"""
    assert comfy_paths.get_user_dir().endswith(os.path.join("ComfyUI", "user"))
    assert comfy_paths.get_output_dir().endswith(os.path.join("ComfyUI", "output"))


def test_folder_paths_branch(monkeypatch):
    """folder_paths 可用时（生产主路径）取 folder_paths 的值。"""
    class FakeFolderPaths:
        def get_user_directory(self):
            return "C:/fp/user"

        def get_output_directory(self):
            return "C:/fp/output"

    monkeypatch.setattr(comfy_paths, "_folder_paths", lambda: FakeFolderPaths())
    assert comfy_paths.get_user_dir() == "C:/fp/user"
    assert comfy_paths.get_output_dir() == "C:/fp/output"
