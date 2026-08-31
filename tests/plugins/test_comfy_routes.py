"""server.register_proxy_routes 幂等性与 _proxy 503 行为测试。"""
import asyncio

from aiohttp.test_utils import make_mocked_request

import artmirror_embed
import comfy_routes as server


class _FakeRouteTable:
    """模拟 aiohttp RouteTableDef 的最小桩：记录注册的路由条目。"""

    def __init__(self):
        self._items = []

    def _register(self, method, path, handler):
        self._items.append((method, path, handler))
        return handler

    def get(self, path):
        return lambda h: self._register("get", path, h)

    def post(self, path):
        return lambda h: self._register("post", path, h)

    def delete(self, path):
        return lambda h: self._register("delete", path, h)


class _FakeInstance:
    def __init__(self):
        self.routes = _FakeRouteTable()


def test_register_proxy_routes_idempotent(monkeypatch):
    """重复调用 register_proxy_routes 不重复追加路由。"""
    instance = _FakeInstance()
    monkeypatch.setattr(server, "_HAVE_COMFY", True)
    monkeypatch.setattr(server, "PromptServer", type("FakePS", (), {"instance": instance}))

    server.register_proxy_routes()
    first = len(instance.routes._items)
    assert first > 0

    server.register_proxy_routes()
    assert len(instance.routes._items) == first


def test_register_proxy_routes_noop_without_comfy(monkeypatch):
    """非 ComfyUI 环境（_HAVE_COMFY=False）时不注册路由。"""
    instance = _FakeInstance()
    monkeypatch.setattr(server, "_HAVE_COMFY", False)
    monkeypatch.setattr(server, "PromptServer", type("FakePS", (), {"instance": instance}))

    server.register_proxy_routes()
    assert instance.routes._items == []


def test_proxy_503_when_embed_not_started(monkeypatch):
    """embed 未启动且 start 失败时 _proxy 返回 503（指向 ComfyUI 控制台日志）。"""
    monkeypatch.setattr(artmirror_embed, "get_url", lambda: None)
    monkeypatch.setattr(artmirror_embed, "start", lambda: None)
    request = make_mocked_request("GET", "/artmirror/gallery.html")
    resp = asyncio.run(server._proxy(request))
    assert resp.status == 503
    assert "ComfyUI 控制台日志" in resp.text
