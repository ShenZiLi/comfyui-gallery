"""扫描任务协调器的并发与合并行为。"""
import threading
import time
from pathlib import Path

from artmirror.services.scanner import ScanStats
from artmirror.services.scan_tasks import ScanCoordinator


def _wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def test_active_scan_merges_new_roots_and_coalesces_duplicates():
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def runner(root, reparse_missing, progress):
        calls.append((root, reparse_missing))
        if root.name == "one":
            entered.set()
            assert release.wait(2)
        stats = ScanStats(files_total=1, files_done=1, new=1)
        progress(stats)
        return stats

    coordinator = ScanCoordinator(runner)
    first = coordinator.request([Path("one")], source="add")
    assert entered.wait(2)
    merged = coordinator.request([Path("one"), Path("two"), Path("two")], source="manual")
    assert merged["task_id"] == first["task_id"]
    assert merged["source"] == "manual"
    release.set()
    _wait_for(lambda: coordinator.status(first["task_id"])["status"] == "completed")

    assert [root.name for root, _ in calls] == ["one", "two"]
    assert calls[1][1] is True
    status = coordinator.status(first["task_id"])
    assert status["files_done"] == status["files_total"] == 2
    assert status["stats"]["new"] == 2


def test_watcher_does_not_queue_overlapping_scan():
    entered = threading.Event()
    release = threading.Event()

    def runner(root, reparse_missing, progress):
        entered.set()
        release.wait(2)
        return ScanStats()

    coordinator = ScanCoordinator(runner)
    active = coordinator.request([Path("one")], source="add")
    assert entered.wait(2)
    assert coordinator.request([Path("two")], source="watcher") is None
    release.set()
    _wait_for(lambda: coordinator.status(active["task_id"])["status"] == "completed")


def test_task_ids_do_not_collide_after_service_restart():
    def runner(root, reparse_missing, progress):
        return ScanStats()

    first = ScanCoordinator(runner).request([Path("one")], source="manual")
    second = ScanCoordinator(runner).request([Path("two")], source="manual")
    assert first["task_id"] != second["task_id"]
