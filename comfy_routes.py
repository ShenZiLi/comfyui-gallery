"""ComfyUI PromptServer 路由：/artmirror/* → 反向代理到进程内 ArtMirror。

模块名避免与 ComfyUI 根目录的 server.py 冲突（同名会导致 sys.path 命中歧义）。
"""
from aiohttp import web

import artmirror_embed
import proxy

try:
    from server import PromptServer  # ComfyUI 主程序已先 import，sys.modules 复用
    _HAVE_COMFY = True
except Exception:  # noqa: BLE001
    PromptServer = None
    _HAVE_COMFY = False


async def _proxy(request: web.Request) -> web.StreamResponse:
    target = artmirror_embed.get_url()
    if target is None:
        port = artmirror_embed.start()
        if port is None:
            return web.Response(status=503, text="ArtMirror 启动失败，请查看 ComfyUI 控制台日志")
        target = f"http://127.0.0.1:{port}"
        artmirror_embed.ensure_default_scan_root()
    proxy.set_target(target)  # 幂等刷新目标，避免 get_url/get_target 状态分歧导致的假 503
    return await proxy.handler(request)


async def _root(request: web.Request) -> web.StreamResponse:
    return web.Response(status=302, headers={"Location": "/artmirror/gallery.html"})


def register_proxy_routes() -> None:
    """在 ComfyUI PromptServer 上注册 /artmirror 路由（仅 ComfyUI 环境，幂等）。"""
    if not _HAVE_COMFY or PromptServer is None:
        return
    instance = PromptServer.instance
    if getattr(instance, "_am_routes_registered", False):
        return
    routes = instance.routes
    for method in ("get", "post", "delete"):
        getattr(routes, method)("/artmirror")(_root)
        getattr(routes, method)("/artmirror/{tail:.*}")(_proxy)
    instance._am_routes_registered = True
