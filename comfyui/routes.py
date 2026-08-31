"""ComfyUI PromptServer 路由：/artmirror/* → 反向代理到进程内 ArtMirror。

本模块合并原 proxy.py 的反向代理实现与路由注册，避免根目录散落过多模块；
模块名避开 ComfyUI 根目录的 server.py（同名会导致 sys.path 命中歧义）。
"""
import asyncio
import logging

import aiohttp
from aiohttp import web

from . import embed as artmirror_embed

log = logging.getLogger("artmirror.proxy")

_target = None  # 例如 http://127.0.0.1:54321


def set_target(base_url: str | None) -> None:
    """设置反向代理目标基址（None 表示未就绪）。"""
    global _target
    _target = base_url.rstrip("/") if base_url else None


def get_target() -> str | None:
    return _target


async def handler(request: web.Request) -> web.StreamResponse:
    """转发 /artmirror/{tail} 到目标后端，透传方法/头/body/query。"""
    target = get_target()
    if target is None:
        return web.Response(status=503, text="ArtMirror 后端未就绪")

    tail = request.match_info.get("tail", "")
    if not tail:
        return web.Response(status=302, headers={"Location": "/artmirror/gallery.html"})

    # query string 必须透传：分页/筛选/排序参数（offset/limit/q/folder_id 等）都在其中，
    # 否则后端永远按默认参数返回第一页，导致前端无限滚动反复加载同一页、表现为卡住。
    qs = request.query_string
    url = f"{target}/{tail}" + (f"?{qs}" if qs else "")
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in (
            "host", "content-length", "connection",
            "transfer-encoding", "upgrade",
        )
    }
    body = await request.read() if request.can_read_body else None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(request.method, url, headers=headers, data=body) as resp:
                response = web.StreamResponse(
                    status=resp.status,
                    headers={"Content-Type": resp.content_type or "application/octet-stream"},
                )
                await response.prepare(request)
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    await response.write(chunk)
                await response.write_eof()
                return response
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        log.error("ArtMirror 后端不可达: %s %s: %s", request.method, url, exc)
        return web.Response(status=502, text="ArtMirror 后端不可达")


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
    set_target(target)  # 幂等刷新目标，避免 get_url/get_target 状态分歧导致的假 503
    return await handler(request)


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
