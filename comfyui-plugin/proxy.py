"""/artmirror/* 反向代理：转发到进程内 ArtMirror（目标由 set_target 提供）。

测试/脱离 ComfyUI 时经 set_target 指向目标基址；ComfyUI 环境由 server.py 注入。
"""
import asyncio
import logging

import aiohttp
from aiohttp import web

log = logging.getLogger("artmirror.proxy")

_target = None  # 例如 http://127.0.0.1:54321


def set_target(base_url: str | None) -> None:
    global _target
    _target = base_url.rstrip("/") if base_url else None


def get_target() -> str | None:
    return _target


async def handler(request: web.Request) -> web.StreamResponse:
    target = get_target()
    if target is None:
        return web.Response(status=503, text="ArtMirror 后端未就绪")

    tail = request.match_info.get("tail", "")
    if not tail:
        return web.Response(status=302, headers={"Location": "/artmirror/gallery.html"})

    url = f"{target}/{tail}"
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
