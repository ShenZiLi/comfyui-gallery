"""系统路由测试：/api/shutdown 优雅关闭接口。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import system


class FakeServer:
    """模拟 uvicorn.Server：run.py 会把真实实例挂到 app.state.server。"""

    def __init__(self):
        self.should_exit = False


def _client(with_server=False):
    app = FastAPI()
    app.include_router(system.router)
    if with_server:
        app.state.server = FakeServer()
    return TestClient(app)


def test_shutdown_dev_mode():
    """开发态（无 server 实例）：返回 200 与开发提示，不报错。"""
    r = _client(False).post("/api/shutdown")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "开发模式" in r.json()["message"]


def test_shutdown_packaged_mode():
    """打包态（有 server 实例）：设置 should_exit=True 触发优雅退出。"""
    c = _client(True)
    server = c.app.state.server
    r = c.post("/api/shutdown")
    assert r.status_code == 200
    assert server.should_exit is True
