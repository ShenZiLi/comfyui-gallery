"""ComfyUI-ArtMirror：画镜 ArtMirror 图库插件。"""
import logging

log = logging.getLogger("artmirror.plugin")

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
        from . import server as _server
        _server.register_proxy_routes()
    except Exception:  # noqa: BLE001
        log.warning("ArtMirror 路由未挂载（非 ComfyUI 环境）", exc_info=True)


_register_routes()
