"""ComfyUI 路径适配器测试（可注入，脱离 ComfyUI 运行）。"""
import os

import comfy_paths


def test_set_paths_override():
    """显式注入路径后，get_user_dir/get_output_dir 返回注入值。"""
    comfy_paths.set_paths("C:/u", "C:/out")
    assert comfy_paths.get_user_dir() == "C:/u"
    assert comfy_paths.get_output_dir() == "C:/out"


def test_fallback_defaults():
    """未注入且无 ComfyUI 时回退到 ~/ComfyUI。"""
    comfy_paths.set_paths(None, None)
    assert comfy_paths.get_user_dir().endswith(os.path.join("ComfyUI", "user"))
    assert comfy_paths.get_output_dir().endswith(os.path.join("ComfyUI", "output"))
