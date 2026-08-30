"""ComfyUI 目录路径适配器。

优先级：set_paths 显式注入 > ComfyUI folder_paths > ~/ComfyUI 回退。
未安装（单测/独立运行）时走回退，也可用 set_paths 显式注入。
"""
import os

_user_dir = None
_output_dir = None


def set_paths(user_dir, output_dir):
    """显式注入路径（测试与特殊部署用）；传 None 表示未注入。"""
    global _user_dir, _output_dir
    _user_dir = user_dir
    _output_dir = output_dir


def _folder_paths():
    try:
        import folder_paths
        return folder_paths
    except ImportError:
        # 非 ComfyUI 环境（folder_paths 未安装）属预期，回退默认目录
        return None


def get_user_dir() -> str:
    if _user_dir is not None:
        return _user_dir
    fp = _folder_paths()
    if fp is not None:
        return fp.get_user_directory()
    return os.path.join(os.path.expanduser("~"), "ComfyUI", "user")


def get_output_dir() -> str:
    if _output_dir is not None:
        return _output_dir
    fp = _folder_paths()
    if fp is not None:
        return fp.get_output_directory()
    return os.path.join(os.path.expanduser("~"), "ComfyUI", "output")
