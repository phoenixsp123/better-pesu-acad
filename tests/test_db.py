"""
Unit tests for local SQLite database functionality.
"""

import tempfile
from pathlib import Path
from backend.db import Database


def test_db_init_and_profile():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path)

        # Initially profile is None
        assert db.get_profile() is None

        # Save profile
        profile = {
            "name": "Jane Student",
            "srn": "PES1UG22CS001",
            "prn": "PES1202200001",
            "branch": "Computer Science",
            "semester": "Sem-5",
            "section": "A",
            "campus": "PES University (Ring Road)",
            "email": "jane@pesu.pes.edu",
            "auth_provider": "credentials"
        }
        db.save_profile(profile)

        saved = db.get_profile()
        assert saved is not None
        assert saved["name"] == "Jane Student"
        assert saved["srn"] == "PES1UG22CS001"
        assert saved["semester"] == "Sem-5"

        db.clear_profile()
        assert db.get_profile() is None


def test_attendance_and_history():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")

        db.upsert_attendance("CS201", "Data Structures", 32, 40, 75.0, source="scraped")
        records = db.get_all_attendance()
        assert len(records) == 1
        assert records[0]["subject_code"] == "CS201"
        assert records[0]["attended"] == 32
        assert records[0]["conducted"] == 40
        assert records[0]["percentage"] == 80.0
        assert records[0]["target_percentage"] == 75.0

        # Change target
        db.set_attendance_target("CS201", 85.0)
        rec = db.get_attendance("CS201")
        assert rec["target_percentage"] == 85.0

        # Delete
        db.delete_attendance("CS201")
        assert len(db.get_all_attendance()) == 0


def test_assignments_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")

        db.save_assignment(
            assignment_id="asg-1",
            title="Lab 3 Graphs",
            subject="Algorithms",
            due_date="2026-11-15",
            priority="high",
            notes="Implement Dijkstra"
        )
        asgs = db.get_assignments()
        assert len(asgs) == 1
        assert asgs[0]["title"] == "Lab 3 Graphs"
        assert asgs[0]["status"] == "pending"

        db.update_assignment_status("asg-1", completed=True)
        asgs = db.get_assignments()
        assert asgs[0]["status"] == "completed"

        db.delete_assignment("asg-1")
        assert len(db.get_assignments()) == 0


def test_study_sessions_and_stats():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")

        db.record_study_session(mode="focus", duration_seconds=1500, subject="OS")
        db.record_study_session(mode="focus", duration_seconds=3000, subject="OS")
        db.record_study_session(mode="short", duration_seconds=300, subject=None)

        stats = db.get_study_stats()
        assert stats["total_completed_sessions"] == 2
        # (1500 + 3000) / 60 = 75 minutes
        assert stats["total_focus_minutes"] == 75.0
        assert stats["today_focus_minutes"] == 75.0
        assert len(stats["subject_breakdown"]) == 1
        assert stats["subject_breakdown"][0]["subj"] == "OS"


def test_bookmarks_and_recent_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")

        db.add_bookmark("Sem-3/OS/L1.pdf", "Lecture 1 OS", page_number=5, notes="Intro slide")
        assert db.is_bookmarked("Sem-3/OS/L1.pdf")
        bms = db.get_bookmarks()
        assert len(bms) == 1
        assert bms[0]["page_number"] == 5

        db.record_recent_file("Sem-3/OS/L1.pdf", "Lecture 1 OS", breadcrumb="Sem-3 / OS", last_page=12)
        recents = db.get_recent_files()
        assert len(recents) == 1
        assert recents[0]["last_page"] == 12

        db.remove_bookmark("Sem-3/OS/L1.pdf")
        assert not db.is_bookmarked("Sem-3/OS/L1.pdf")
