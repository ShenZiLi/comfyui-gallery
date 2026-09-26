"""单进程图片扫描任务协调器。"""
from __future__ import annotations

import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Callable

from sqlmodel import Session

from ..database import get_engine, normalize_path_key
from . import scanner


Runner = Callable[[Path, bool, Callable[[scanner.ScanStats], None]], scanner.ScanStats]


def _run_root(root: Path, reparse_missing: bool, progress) -> scanner.ScanStats:
    with Session(get_engine()) as session:
        return scanner.scan(
            session,
            root,
            reparse_missing=reparse_missing,
            progress=progress,
        )


class ScanCoordinator:
    """合并重复根目录请求，并保证最多一个扫描线程运行。"""

    def __init__(self, runner: Runner = _run_root):
        self._runner = runner
        self._lock = threading.RLock()
        self._tasks: dict[str, dict] = {}
        self._active_id: str | None = None
        self._sequence = 0
        self._instance_id = uuid.uuid4().hex[:10]

    def request(self, roots: list[Path], *, source: str, reparse_missing: bool = True):
        roots = [Path(root).resolve() for root in roots]
        if not roots:
            return None
        with self._lock:
            if source == "watcher" and self._active_id is not None:
                return None
            if self._active_id is not None:
                task = self._tasks[self._active_id]
                if source != "watcher":
                    task["source"] = source
                task["reparse_missing"] = task["reparse_missing"] or reparse_missing
                for root in roots:
                    key = normalize_path_key(str(root))
                    if key not in task["scheduled"]:
                        task["scheduled"].add(key)
                        task["pending"].append(root)
                        task["roots_total"] += 1
                return self._public(task)

            self._sequence += 1
            task_id = f"{self._instance_id}-{self._sequence}"
            task = {
                "task_id": task_id,
                "status": "queued",
                "phase": "counting",
                "source": source,
                "reparse_missing": reparse_missing,
                "pending": deque(),
                "scheduled": set(),
                "current_root": "",
                "current_file": "",
                "files_done": 0,
                "files_total": 0,
                "roots_done": 0,
                "roots_total": 0,
                "stats": {"new": 0, "updated": 0, "skipped": 0, "removed": 0, "parsed": 0},
                "errors": [],
                "failed": False,
            }
            self._tasks[task_id] = task
            self._active_id = task_id
            for root in roots:
                key = normalize_path_key(str(root))
                if key not in task["scheduled"]:
                    task["scheduled"].add(key)
                    task["pending"].append(root)
                    task["roots_total"] += 1
            thread = threading.Thread(target=self._work, args=(task_id,), daemon=True, name="am-scan")
            task["thread"] = thread
            thread.start()
            return self._public(task)

    def _work(self, task_id: str) -> None:
        while True:
            with self._lock:
                task = self._tasks.get(task_id)
                if task is None:
                    return
                if not task["pending"]:
                    task["status"] = "failed" if task["failed"] else "completed"
                    task["phase"] = task["status"]
                    task["current_root"] = ""
                    task["current_file"] = ""
                    if self._active_id == task_id:
                        self._active_id = None
                    self._prune()
                    return
                root = task["pending"].popleft()
                task["status"] = "running"
                task["phase"] = "counting"
                task["current_root"] = str(root)
                task["current_file"] = ""
                base_total = task["files_total"]
                base_done = task["files_done"]

            def on_progress(stats: scanner.ScanStats) -> None:
                with self._lock:
                    current = self._tasks.get(task_id)
                    if current is None:
                        return
                    current["phase"] = "running"
                    current["files_total"] = base_total + stats.files_total
                    current["files_done"] = base_done + stats.files_done
                    current["current_file"] = stats.current_file

            try:
                stats = self._runner(root, task["reparse_missing"], on_progress)
                with self._lock:
                    current = self._tasks.get(task_id)
                    if current is None:
                        return
                    current["files_total"] = max(
                        current["files_total"], base_total + stats.files_total
                    )
                    current["files_done"] = max(
                        current["files_done"], base_done + stats.files_done
                    )
                    current["roots_done"] += 1
                    for name in current["stats"]:
                        current["stats"][name] += getattr(stats, name)
                    current["errors"].extend(stats.errors)
                    current["current_file"] = ""
                    source = current["source"]
                if stats.new or stats.updated or stats.removed:
                    from . import watcher
                    if source == "watcher" and stats.new and not (stats.updated or stats.removed):
                        watcher._bump()
                    else:
                        watcher.bump()
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    task = self._tasks.get(task_id)
                    if task is not None:
                        task["errors"].append(f"{root}: {exc}")
                        task["failed"] = True
                        task["roots_done"] += 1

    def status(self, task_id: str):
        with self._lock:
            task = self._tasks.get(task_id)
            return self._public(task) if task else None

    def active(self):
        with self._lock:
            if self._active_id is None:
                return None
            return self._public(self._tasks[self._active_id])

    def _public(self, task: dict) -> dict:
        return {
            "task_id": task["task_id"],
            "status": task["status"],
            "phase": task["phase"],
            "source": task["source"],
            "current_root": task["current_root"],
            "current_file": task["current_file"],
            "files_done": task["files_done"],
            "files_total": task["files_total"],
            "roots_done": task["roots_done"],
            "roots_total": task["roots_total"],
            "stats": dict(task["stats"]),
            "errors": list(task["errors"]),
        }

    def _prune(self) -> None:
        finished = [
            task_id for task_id, task in self._tasks.items()
            if task["status"] in {"completed", "failed"}
        ]
        for task_id in finished[:-20]:
            self._tasks.pop(task_id, None)


coordinator = ScanCoordinator()


def request_scan(roots: list[Path], *, source: str, reparse_missing: bool = True):
    return coordinator.request(roots, source=source, reparse_missing=reparse_missing)
