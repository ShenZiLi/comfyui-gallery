"""扫描任务 HTTP 接口测试。"""
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine

from artmirror.config import settings
from artmirror.database import get_session
from artmirror.routers import settings as settings_router
from artmirror.services import scan_tasks
from artmirror.services.scanner import ScanStats


def test_manual_scan_api_starts_job_and_exposes_progress(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        settings.data_dir = str(tmp)
        settings.ensure_dirs()
        root = tmp / "outputs"
        root.mkdir()
        engine = create_engine(
            f"sqlite:///{tmp / 'tasks.db'}",
            connect_args={"check_same_thread": False},
            poolclass=NullPool,
        )
        SQLModel.metadata.create_all(engine)
        entered, release = __import__("threading").Event(), __import__("threading").Event()

        def runner(path, reparse_missing, progress):
            stats = ScanStats(files_total=4)
            progress(stats)
            entered.set()
            assert release.wait(2)
            stats.files_done = 2
            stats.current_file = str(path / "two.png")
            progress(stats)
            return stats

        coordinator = scan_tasks.ScanCoordinator(runner)
        monkeypatch.setattr(scan_tasks, "coordinator", coordinator)
        app = FastAPI()
        app.include_router(settings_router.router)

        def session_override():
            with Session(engine) as session:
                yield session

        app.dependency_overrides[get_session] = session_override
        with Session(engine) as session:
            from artmirror.services.scanner import save_scan_roots
            save_scan_roots(session, [str(root)])

        client = TestClient(app)
        started = client.post("/api/settings/scans")
        assert started.status_code == 200
        task_id = started.json()["task_id"]
        assert entered.wait(2)
        status = client.get(f"/api/settings/scans/{task_id}").json()
        assert status["status"] == "running"
        assert status["files_total"] == 4
        release.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = client.get(f"/api/settings/scans/{task_id}").json()
            if status["status"] == "completed":
                break
            time.sleep(0.01)
        assert status["files_done"] == 2
        assert client.get("/api/settings/scans/active").json() is None
