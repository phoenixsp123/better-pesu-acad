"""
Unit tests for background sync job manager.
"""

import tempfile
from pathlib import Path
import pytest

from backend.config import Config
from backend.auth.manager import AuthManager
from backend.db import Database
from backend.jobs.sync_manager import SyncManager


def test_sync_manager_initial_state():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Config(data_dir=Path(tmpdir))
        db = Database(cfg.db_path)
        auth = AuthManager(cfg.session_file, db)
        sm = SyncManager(cfg, auth)

        status = sm.get_status()
        assert status["running"] is False
        assert status["phase"] == "idle"
        assert status["progress"] == 0.0


def test_sync_manager_convert_only_job():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Config(data_dir=Path(tmpdir))
        db = Database(cfg.db_path)
        auth = AuthManager(cfg.session_file, db)
        sm = SyncManager(cfg, auth)

        # Convert only job executes immediately
        state = sm.start_sync(convert_only=True)
        assert state["running"] is True

        # Wait for worker thread
        if sm._current_thread:
            sm._current_thread.join(timeout=5)

        final_status = sm.get_status()
        assert final_status["running"] is False
        assert final_status["phase"] == "complete"
        assert final_status["progress"] == 100.0


def test_sync_manager_cancel():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Config(data_dir=Path(tmpdir))
        db = Database(cfg.db_path)
        auth = AuthManager(cfg.session_file, db)
        sm = SyncManager(cfg, auth)

        # Calling cancel when not running returns False
        assert sm.cancel() is False
