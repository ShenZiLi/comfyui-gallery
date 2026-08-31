"""ArtMirror：画镜 ComfyUI 图库插件。

本仓库根目录即 ComfyUI 自定义节点包（custom node）——
clone 后直接放入 ComfyUI/custom_nodes/ArtMirror 重启即用：
  - WEB_DIRECTORY 注册侧边栏「图库」tab（web/artmirror-tab.js）
  - requirements.txt 由 ComfyUI 启动时自动安装依赖
  - 核心后端复用根目录 artmirror/ 包，随 ComfyUI 进程内启动（临时端口）
  - /artmirror/* 反向代理由 comfy_routes.py 注册到 ComfyUI PromptServer
"""
import logging
import sys
from pathlib import Path

log = logging.getLogger("artmirror.plugin")

# 本地包引导：ComfyUI 0.33+ 的 load_custom_node 不把 custom node 目录加入 sys.path，
# 需显式注入，否则 artmirror / artmirror_embed 等本地包绝对导入失败。
_plugin_dir = str(Path(__file__).resolve().parent)
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

# 前端扩展目录（WEB_DIRECTORY 仅服务 .js，HTML 前端由后端路由托管）
WEB_DIRECTORY = "web"


class ArtMirrorLauncher:
    """占位节点：使包被 ComfyUI 识别为自定义节点包（NODE_CLASS_MAPPINGS 非空）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ()
    FUNCTION = "noop"
    CATEGORY = "ArtMirror"

    def noop(self):
        return ()


NODE_CLASS_MAPPINGS = {"ArtMirrorLauncher": ArtMirrorLauncher}
NODE_DISPLAY_NAME_MAPPINGS = {"ArtMirrorLauncher": "ArtMirror 图库"}


def _register_routes():
    """挂载 /artmirror/* 路由（懒加载：仅 ComfyUI 环境可用时）。"""
    try:
        import comfy_routes as _routes
        _routes.register_proxy_routes()
    except ImportError:
        # 非 ComfyUI 环境（comfy_routes 模块不可用）属预期，静默跳过
        log.debug("ArtMirror 路由未挂载（非 ComfyUI 环境）")
    except Exception:  # noqa: BLE001
        # ComfyUI 环境内的真实异常需暴露，避免掩盖 bug
        log.warning("ArtMirror 路由挂载失败", exc_info=True)


_register_routes()
