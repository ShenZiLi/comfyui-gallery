"""进程内 ArtMirror 启动线程测试。"""
import tempfile
from pathlib import Path

import httpx
import pytest

import artmirror_embed
import comfy_paths


@pytest.fixture(autouse=True)
def _reset_inject():
    """每个用例后复位注入状态，消除与 comfy_paths 测试的顺序依赖。"""
    yield
    comfy_paths.set_paths(None, None)


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
    """resolve_data_dir 指向 user/artmirror；resolve_frontend_dir 返回可用前端目录。"""
    with tempfile.TemporaryDirectory() as td:
        comfy_paths.set_paths(str(Path(td) / "user"), str(Path(td) / "out"))
        data = artmirror_embed.resolve_data_dir()
        assert data == str(Path(td) / "user" / "artmirror")
        fe = artmirror_embed.resolve_frontend_dir()
        assert Path(fe).is_dir()


def test_data_dir_override_effective():
    """start() 后 SQLite 库落在 user/artmirror（覆盖真实生效）。"""
    with tempfile.TemporaryDirectory() as td:
        user = Path(td) / "user"
        comfy_paths.set_paths(str(user), str(Path(td) / "out"))
        port = artmirror_embed.start()
        assert port is not None
        assert (user / "artmirror" / "artmirror.db").exists()
        artmirror_embed.stop()


def test_restart_with_new_user_dir():
    """stop 后更换用户目录再 start，DB 落在新目录（_rebind_engine 生效）。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        user_a = td / "userA"
        user_b = td / "userB"
        comfy_paths.set_paths(str(user_a), str(td / "out"))
        assert artmirror_embed.start() is not None
        artmirror_embed.stop()

        comfy_paths.set_paths(str(user_b), str(td / "out"))
        assert artmirror_embed.start() is not None
        assert (user_a / "artmirror" / "artmirror.db").exists()
        assert (user_b / "artmirror" / "artmirror.db").exists()
        artmirror_embed.stop()
