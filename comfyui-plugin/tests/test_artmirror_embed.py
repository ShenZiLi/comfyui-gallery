"""进程内 ArtMirror 启动线程测试。"""
import tempfile
from pathlib import Path

import httpx

import artmirror_embed
import comfy_paths


def test_start_and_health():
    """start() 返回可用端口，/api/health 可访问，stop() 后端口释放。"""
    with tempfile.TemporaryDirectory() as td:
        comfy_paths.set_paths(str(Path(td) / "user"), str(Path(td) / "out"))
        port = artmirror_embed.start()
        assert isinstance(port, int) and port > 0
        r = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=5)
        assert r.status_code == 200
        assert r.json()["app"] == "artmirror"
        assert artmirror_embed.get_url() == f"http://127.0.0.1:{port}"
        artmirror_embed.stop()
        assert artmirror_embed.get_url() is None


def test_start_singleton():
    """重复 start() 返回同一端口，不重复启动。"""
    with tempfile.TemporaryDirectory() as td:
        comfy_paths.set_paths(str(Path(td) / "user"), str(Path(td) / "out"))
        p1 = artmirror_embed.start()
        p2 = artmirror_embed.start()
        assert p1 == p2
        artmirror_embed.stop()


def test_resolve_paths():
    """resolve_data_dir 指向 user/artmirror；resolve_frontend_dir 指向插件内 static。"""
    with tempfile.TemporaryDirectory() as td:
        comfy_paths.set_paths(str(Path(td) / "user"), str(Path(td) / "out"))
        data = artmirror_embed.resolve_data_dir()
        assert data == str(Path(td) / "user" / "artmirror")
        fe = artmirror_embed.resolve_frontend_dir()
        assert fe.endswith("static")
