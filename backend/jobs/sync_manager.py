"""
Unified Background Synchronization Job Manager for Better PESU Acad.
Coordinates downloading course materials and converting PPTX slides to PDF.
Thread-safe, packaging-compatible (runs in-process), cancellation-aware,
with honest progress and ETA reporting.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from backend.config import Config
from backend.jobs.downloader_engine import DownloaderEngine
from backend.jobs.converter_engine import ConverterEngine
from backend.auth.manager import AuthManager

logger = logging.getLogger("betterpesu.sync_manager")


class SyncManager:
    def __init__(self, config: Config, auth_manager: AuthManager):
        self.config = config
        self.auth_manager = auth_manager
        self.downloader = DownloaderEngine(
            session=auth_manager.session,
            slides_dir=config.slides_dir,
            metadata_file=config.courses_json
        )
        self.converter = ConverterEngine(
            slides_dir=config.slides_dir,
            metadata_file=config.courses_json
        )

        self._lock = threading.Lock()
        self._cancel_flag = threading.Event()
        self._current_thread: Optional[threading.Thread] = None

        self._state: Dict[str, Any] = {
            "running": False,
            "phase": "idle",
            "progress": 0.0,
            "eta_seconds": None,
            "current_subject": None,
            "processed": 0,
            "total": None,
            "downloaded": 0,
            "skipped": 0,
            "failed_files": 0,
            "converted": 0,
            "error": None,
            "last_synced": None,
            "selection": None,
        }

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def cancel(self) -> bool:
        with self._lock:
            if not self._state["running"]:
                return False
            self._cancel_flag.set()
            self._state["phase"] = "cancelling"
            return True

    def start_sync(self, selection: Optional[Dict[str, Any]] = None, convert_only: bool = False) -> Dict[str, Any]:
        with self._lock:
            if self._state["running"]:
                raise RuntimeError("A sync job is already currently running")

            self._cancel_flag.clear()
            self._state.update({
                "running": True,
                "phase": "starting",
                "progress": 0.0,
                "eta_seconds": None,
                "current_subject": None,
                "processed": 0,
                "total": None,
                "downloaded": 0,
                "skipped": 0,
                "failed_files": 0,
                "converted": 0,
                "error": None,
                "selection": selection,
            })

            thread = threading.Thread(
                target=self._run_job,
                args=(selection, convert_only),
                daemon=True,
                name="BetterPESU-SyncWorker"
            )
            self._current_thread = thread
            thread.start()

            return dict(self._state)

    def _update_progress(self, event: Dict[str, Any], phase: str, started_at: float) -> None:
        name = event.get("event")
        with self._lock:
            if phase == "downloading":
                if name == "download_plan":
                    self._state["total"] = event.get("total")
                elif name in ("subject_start", "subject_complete", "file"):
                    self._state["current_subject"] = event.get("subject")
                    for k in ("downloaded", "skipped"):
                        if k in event:
                            self._state[k] = event[k]
                    if "failed" in event:
                        self._state["failed_files"] = event["failed"]
                    if name == "subject_complete":
                        done = event["done"]
                        total = event["total"]
                        self._state["processed"] = done
                        self._state["total"] = total
                        # Downloading is 0 to 80% of total job
                        if total:
                            self._state["progress"] = round(80.0 * done / total, 1)
                            elapsed = time.monotonic() - started_at
                            if done and done < total:
                                rate = elapsed / done
                                self._state["eta_seconds"] = max(0, round(rate * (total - done)))
                            else:
                                self._state["eta_seconds"] = None

            elif phase == "converting":
                if name == "conversion_plan":
                    self._state.update(
                        processed=0,
                        total=event.get("total"),
                        progress=80.0,
                        eta_seconds=None,
                        current_subject=None
                    )
                elif name == "conversion_file":
                    done = event["done"]
                    total = event["total"]
                    self._state.update(
                        processed=done,
                        total=total,
                        converted=event.get("converted", 0),
                        progress=round(80.0 + 20.0 * (done / total), 1) if total else 100.0
                    )
                    elapsed = time.monotonic() - started_at
                    if done and done < total:
                        rate = elapsed / done
                        self._state["eta_seconds"] = max(0, round(rate * (total - done)))
                    else:
                        self._state["eta_seconds"] = None

    def _run_job(self, selection: Optional[Dict[str, Any]], convert_only: bool) -> None:
        try:
            semester = selection.get("semester") if selection else None
            subject_id = selection.get("subject_id") if selection else None

            # Phase 1: Download
            if not convert_only:
                with self._lock:
                    self._state.update(phase="downloading", progress=0.0)
                download_start = time.monotonic()

                def download_cb(evt: Dict[str, Any]) -> None:
                    self._update_progress(evt, "downloading", download_start)

                self.downloader.run_sync(
                    selected_semester=semester,
                    selected_subject_id=subject_id,
                    progress_callback=download_cb,
                    is_cancelled=self._cancel_flag.is_set
                )

            if self._cancel_flag.is_set():
                with self._lock:
                    self._state.update(phase="cancelled", running=False)
                return

            # Phase 2: Convert
            with self._lock:
                self._state.update(phase="converting", progress=80.0, processed=0, total=None)
            convert_start = time.monotonic()

            def convert_cb(evt: Dict[str, Any]) -> None:
                self._update_progress(evt, "converting", convert_start)

            self.converter.run_conversion(
                selected_semester=semester,
                selected_subject_id=subject_id,
                progress_callback=convert_cb,
                is_cancelled=self._cancel_flag.is_set
            )

            if self._cancel_flag.is_set():
                with self._lock:
                    self._state.update(phase="cancelled", running=False)
                return

            # Completed successfully
            with self._lock:
                now_iso = datetime.now(timezone.utc).isoformat()
                self._state.update(
                    running=False,
                    phase="complete",
                    progress=100.0,
                    eta_seconds=0,
                    current_subject=None,
                    last_synced=now_iso,
                    error=None
                )

        except Exception as e:
            logger.exception("Sync job encountered an error: %s", e)
            with self._lock:
                self._state.update(
                    running=False,
                    phase="failed",
                    error=str(e),
                    eta_seconds=None
                )
        finally:
            with self._lock:
                self._state["running"] = False
