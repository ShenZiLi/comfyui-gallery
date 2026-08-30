"""/artmirror/* 反向代理核心逻辑测试（不经 ComfyUI，直接挂 aiohttp app）。"""
import asyncio
import json
import tempfile
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import artmirror_embed
import comfy_paths
import proxy


def _make_app() -> web.Application:
    app = web.Application()

    async def root(request):
        return web.HTTPFound("/artmirror/gallery.html")

    async def catch(request):
        return await proxy.handler(request)

    app.router.add_get("/artmirror", root)
    app.router.add_get("/artmirror/{tail:.*}", catch)
    app.router.add_post("/artmirror/{tail:.*}", catch)
    return app


def _check(path, method="GET", expect=200):
    """同步封装：启动 embed → 起代理 client → 请求断言 → 清理。"""
    async def run():
        with tempfile.TemporaryDirectory() as td:
            comfy_paths.set_paths(str(Path(td) / "user"), str(Path(td) / "out"))
            port = artmirror_embed.start()
            proxy.set_target(f"http://127.0.0.1:{port}")
            client = TestClient(TestServer(_make_app()))
            await client.start_server()
            try:
                r = await client.request(method, path, allow_redirects=False)
                body = await r.read()
                return r.status, r.headers, body
            finally:
                await client.close()
                artmirror_embed.stop()
    status, headers, body = asyncio.run(run())
    assert status == expect, f"status={status}"
    return status, headers, body


def test_proxy_health():
    _, _, body = _check("/artmirror/api/health")
    assert json.loads(body)["app"] == "artmirror"


def test_proxy_redirect():
    _, headers, _ = _check("/artmirror", expect=302)
    assert headers["Location"] == "/artmirror/gallery.html"


def test_proxy_static():
    _, _, body = _check("/artmirror/gallery.html")
    assert "画镜" in body.decode("utf-8", "ignore")
