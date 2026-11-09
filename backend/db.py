"""
SQLite database layer for Better PESU Acad.
Stores attendance snapshots, student profile, assignments, bookmarks,
recent documents, study sessions, timetable, and settings locally.
"""

from __future__ import annotations

import sqlite3
import json
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("betterpesu.db")


class Database:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._migrate_schema()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS student_profile (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    name TEXT,
                    srn TEXT,
                    prn TEXT,
                    branch TEXT,
                    semester TEXT,
                    section TEXT,
                    campus TEXT,
                    email TEXT,
                    avatar_url TEXT,
                    auth_provider TEXT DEFAULT 'credentials',
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS attendance (
                    subject_code TEXT PRIMARY KEY,
                    subject_name TEXT NOT NULL,
                    semester TEXT DEFAULT '',
                    attended INTEGER NOT NULL DEFAULT 0,
                    conducted INTEGER NOT NULL DEFAULT 0,
                    percentage REAL NOT NULL DEFAULT 0.0,
                    target_percentage REAL NOT NULL DEFAULT 75.0,
                    source TEXT DEFAULT 'scraped',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS attendance_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_code TEXT NOT NULL,
                    snapshot_date TEXT NOT NULL,
                    attended INTEGER NOT NULL,
                    conducted INTEGER NOT NULL,
                    percentage REAL NOT NULL,
                    FOREIGN KEY (subject_code) REFERENCES attendance (subject_code) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS isa_marks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_code TEXT NOT NULL,
                    subject_name TEXT NOT NULL,
                    semester TEXT DEFAULT '',
                    credits REAL DEFAULT 4.0,
                    isa1_score REAL,
                    isa1_max REAL DEFAULT 40.0,
                    isa2_score REAL,
                    isa2_max REAL DEFAULT 40.0,
                    assignment_score REAL,
                    assignment_max REAL DEFAULT 10.0,
                    project_or_lab REAL,
                    project_max REAL DEFAULT 10.0,
                    cie_total REAL,
                    source TEXT DEFAULT 'scraped',
                    updated_at TEXT NOT NULL,
                    UNIQUE(subject_code, semester)
                );

                CREATE TABLE IF NOT EXISTS timetable (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    day_of_week INTEGER NOT NULL, -- 0=Monday, 6=Sunday
                    period_number INTEGER NOT NULL,
                    start_time TEXT,
                    end_time TEXT,
                    subject_code TEXT,
                    subject_name TEXT NOT NULL,
                    room TEXT,
                    is_lab BOOLEAN DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS assignments (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    due_date TEXT NOT NULL,
                    priority TEXT DEFAULT 'medium', -- low, medium, high
                    status TEXT DEFAULT 'pending',   -- pending, completed
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bookmarks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    page_number INTEGER DEFAULT 1,
                    notes TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS recent_files (
                    file_path TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    breadcrumb TEXT,
                    last_page INTEGER DEFAULT 1,
                    last_viewed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS study_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL, -- focus, short, long
                    duration_seconds INTEGER NOT NULL,
                    subject TEXT,
                    completed_at TEXT NOT NULL,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            conn.commit()

    def _migrate_schema(self) -> None:
        """Safely ensure new columns and tables exist without data loss."""
        with self.get_connection() as conn:
            try:
                cols = [r["name"] for r in conn.execute("PRAGMA table_info(attendance)").fetchall()]
                if "semester" not in cols:
                    conn.execute("ALTER TABLE attendance ADD COLUMN semester TEXT DEFAULT ''")

                # Clean legacy attendance records where semester was empty
                conn.execute("""
                    UPDATE attendance 
                    SET semester = 'Sem-1' 
                    WHERE (semester IS NULL OR semester = '') 
                      AND (subject_code LIKE '%141%' OR subject_code LIKE '%151%' OR subject_code LIKE '%121%' OR subject_code LIKE 'UE__CS1%' OR subject_code LIKE 'UE__EE1%' OR subject_code LIKE 'UE__MA1%' OR subject_code LIKE 'UE__PH1%' OR subject_code LIKE 'UE__ME1%')
                """)
                conn.execute("""
                    UPDATE attendance 
                    SET semester = 'Sem-3' 
                    WHERE (semester IS NULL OR semester = '') 
                      AND (subject_code LIKE '%242%' OR subject_code LIKE '%243%' OR subject_code LIKE '%251%' OR subject_code LIKE '%252%' OR subject_code LIKE 'UE__CS2%' OR subject_code LIKE 'UE__MA2%')
                """)

                # Clean legacy isa_marks records where semester was empty
                conn.execute("""
                    UPDATE isa_marks 
                    SET semester = 'Sem-1' 
                    WHERE (semester IS NULL OR semester = '') 
                      AND (subject_code LIKE '%141%' OR subject_code LIKE '%151%' OR subject_code LIKE '%121%' OR subject_code LIKE 'UE__CS1%' OR subject_code LIKE 'UE__EE1%' OR subject_code LIKE 'UE__MA1%' OR subject_code LIKE 'UE__PH1%' OR subject_code LIKE 'UE__ME1%')
                """)
                conn.execute("""
                    UPDATE isa_marks 
                    SET semester = 'Sem-3' 
                    WHERE (semester IS NULL OR semester = '') 
                      AND (subject_code LIKE '%242%' OR subject_code LIKE '%243%' OR subject_code LIKE '%251%' OR subject_code LIKE '%252%' OR subject_code LIKE 'UE__CS2%' OR subject_code LIKE 'UE__MA2%' OR subject_code LIKE 'UZ__UZ2%')
                """)

                # Clean legacy timetable records if they contain 'ttSubject'
                tt_rows = conn.execute("SELECT id, subject_code, subject_name, start_time, end_time FROM timetable").fetchall()
                for r in tt_rows:
                    raw_name = r["subject_name"] or ""
                    code = r["subject_code"] or ""
                    st = r["start_time"] or ""
                    et = r["end_time"] or ""

                    needs_update = False
                    cleaned_name = re.sub(r'^(?:ttSubject)?[_&]+', '', raw_name).strip()
                    if cleaned_name != raw_name:
                        needs_update = True

                    m = re.match(r'^([A-Z0-9]{5,12})\s*[-–—:]\s*(.+)$', cleaned_name, re.IGNORECASE)
                    if m:
                        code = m.group(1).strip()
                        cleaned_name = m.group(2).strip()
                        needs_update = True

                    if cleaned_name.isupper():
                        words = cleaned_name.split()
                        cleaned_name = " ".join(
                            w.upper() if w.lower() in ("ai", "i", "ii", "iii", "iv", "ml", "os", "dsa")
                            else (w.lower() if w.lower() in ("and", "for", "in", "of", "to", "the", "its", "with")
                                  else w.capitalize())
                            for w in words
                        )
                        needs_update = True

                    # Remove seconds from time: '08:00:16 AM' -> '08:00 AM'
                    new_st = re.sub(r'^(\d{1,2}:\d{2}):\d{2}(\s*[AP]M)?$', r'\1\2', st.strip())
                    new_et = re.sub(r'^(\d{1,2}:\d{2}):\d{2}(\s*[AP]M)?$', r'\1\2', et.strip())
                    new_st = re.sub(r'^(\d{1,2})\s*([AP]M)$', r'\1:00 \2', new_st)
                    new_et = re.sub(r'^(\d{1,2})\s*([AP]M)$', r'\1:00 \2', new_et)
                    if new_st != st or new_et != et:
                        needs_update = True

                    if needs_update:
                        conn.execute(
                            "UPDATE timetable SET subject_code = ?, subject_name = ?, start_time = ?, end_time = ? WHERE id = ?",
                            (code, cleaned_name, new_st, new_et, r["id"])
                        )

                conn.commit()
            except Exception as e:
                logger.warning("DB migration check: %s", e)

    # --- Student Profile ---
    def get_profile(self) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM student_profile WHERE id = 1").fetchone()
            if not row:
                return None
            data = dict(row)

            changed = False
            # Clean SRN if prefixed with "SRN :" or "Roll :"
            srn_raw = data.get("srn") or ""
            srn_clean = re.sub(r'^(?:SRN\s*:\s*|Roll\s*:\s*)', '', srn_raw, flags=re.IGNORECASE).strip()
            if srn_clean != srn_raw:
                data["srn"] = srn_clean
                changed = True

            # If semester is empty or "–", infer latest from isa_marks / attendance
            if not data.get("semester") or data.get("semester") in ("–", "-", ""):
                try:
                    sem_row = conn.execute("""
                        SELECT semester FROM isa_marks WHERE semester IS NOT NULL AND semester != ''
                        UNION
                        SELECT semester FROM attendance WHERE semester IS NOT NULL AND semester != ''
                        ORDER BY semester DESC LIMIT 1
                    """).fetchone()
                    if sem_row and sem_row[0]:
                        data["semester"] = sem_row[0]
                        changed = True
                    else:
                        data["semester"] = "Sem-3"
                        changed = True
                except Exception:
                    data["semester"] = "Sem-3"

            # If branch is empty or generic "Engineering", infer from SRN code
            if not data.get("branch") or data.get("branch") in ("Engineering", "–", "-"):
                branch_map = {
                    "CS": "Computer Science and Engineering",
                    "EC": "Electronics and Communication Engineering",
                    "EE": "Electrical and Electronics Engineering",
                    "ME": "Mechanical Engineering",
                    "BT": "Biotechnology",
                    "AI": "Artificial Intelligence & Machine Learning",
                    "AM": "Artificial Intelligence & Machine Learning",
                    "IS": "Information Science and Engineering",
                    "DS": "Data Science",
                    "CV": "Civil Engineering",
                    "CH": "Chemical Engineering",
                }
                match = re.search(r'PES\d(?:UG|PG)\d\d([A-Z]{2})', data.get("srn", ""), re.IGNORECASE)
                if match and match.group(1).upper() in branch_map:
                    data["branch"] = branch_map[match.group(1).upper()]
                    changed = True
                else:
                    data["branch"] = "Computer Science and Engineering"
                    changed = True

            # Campus refinement
            if not data.get("campus") or data.get("campus") in ("PES University", "–", "-"):
                if "PES2" in (data.get("srn") or "").upper():
                    data["campus"] = "PES University (Electronic City)"
                else:
                    data["campus"] = "PES University (Ring Road)"
                changed = True

            # Persist back inferred fields if changed
            if changed:
                try:
                    conn.execute("""
                        UPDATE student_profile SET
                            srn = ?,
                            semester = ?,
                            branch = ?,
                            campus = ?,
                            updated_at = ?
                        WHERE id = 1
                    """, (
                        data.get("srn"),
                        data.get("semester"),
                        data.get("branch"),
                        data.get("campus"),
                        datetime.now(timezone.utc).isoformat()
                    ))
                    conn.commit()
                except Exception as e:
                    logger.debug("Could not persist auto-resolved profile fields: %s", e)

            return data

    def save_profile(self, profile_data: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO student_profile (
                    id, name, srn, prn, branch, semester, section, campus, email, avatar_url, auth_provider, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    srn = excluded.srn,
                    prn = excluded.prn,
                    branch = excluded.branch,
                    semester = excluded.semester,
                    section = excluded.section,
                    campus = excluded.campus,
                    email = excluded.email,
                    avatar_url = excluded.avatar_url,
                    auth_provider = excluded.auth_provider,
                    updated_at = excluded.updated_at
            """, (
                profile_data.get("name"),
                profile_data.get("srn"),
                profile_data.get("prn"),
                profile_data.get("branch"),
                profile_data.get("semester"),
                profile_data.get("section"),
                profile_data.get("campus"),
                profile_data.get("email"),
                profile_data.get("avatar_url"),
                profile_data.get("auth_provider", "credentials"),
                now
            ))
            conn.commit()

    def clear_profile(self) -> None:
        with self.get_connection() as conn:
            conn.execute("DELETE FROM student_profile WHERE id = 1")
            conn.commit()

    # --- Attendance ---
    def get_all_attendance(self, semester: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            if semester and semester.strip() and semester.strip().lower() not in ("all", "all semesters", "all_semesters"):
                rows = conn.execute(
                    "SELECT * FROM attendance WHERE LOWER(semester) = LOWER(?) ORDER BY subject_name ASC",
                    (semester.strip(),)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM attendance ORDER BY semester ASC, subject_name ASC").fetchall()
            return [dict(r) for r in rows]

    def get_attendance(self, subject_code: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM attendance WHERE subject_code = ?", (subject_code,)).fetchone()
            return dict(row) if row else None

    def upsert_attendance(
        self,
        subject_code: str,
        subject_name: str,
        attended: int,
        conducted: int,
        target_percentage: float = 75.0,
        source: str = "scraped",
        semester: str = ""
    ) -> None:
        pct = (attended / conducted * 100.0) if conducted > 0 else 0.0
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO attendance (
                    subject_code, subject_name, semester, attended, conducted, percentage, target_percentage, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subject_code) DO UPDATE SET
                    subject_name = excluded.subject_name,
                    semester = CASE WHEN excluded.semester != '' THEN excluded.semester ELSE attendance.semester END,
                    attended = excluded.attended,
                    conducted = excluded.conducted,
                    percentage = excluded.percentage,
                    target_percentage = COALESCE(attendance.target_percentage, excluded.target_percentage),
                    source = excluded.source,
                    updated_at = excluded.updated_at
            """, (subject_code, subject_name, semester, attended, conducted, round(pct, 2), target_percentage, source, now))

            # Record snapshot in history
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            conn.execute("""
                INSERT INTO attendance_history (subject_code, snapshot_date, attended, conducted, percentage)
                VALUES (?, ?, ?, ?, ?)
            """, (subject_code, today, attended, conducted, round(pct, 2)))
            conn.commit()

    def set_attendance_target(self, subject_code: str, target: float) -> None:
        with self.get_connection() as conn:
            conn.execute("UPDATE attendance SET target_percentage = ? WHERE subject_code = ?", (target, subject_code))
            conn.commit()

    def delete_attendance(self, subject_code: str) -> None:
        with self.get_connection() as conn:
            conn.execute("DELETE FROM attendance WHERE subject_code = ?", (subject_code,))
            conn.commit()

    def clear_attendance(self, semester: Optional[str] = None) -> None:
        with self.get_connection() as conn:
            if semester and semester.strip():
                conn.execute("DELETE FROM attendance WHERE semester = ?", (semester.strip(),))
            else:
                conn.execute("DELETE FROM attendance")
            conn.commit()

    # --- ISA Results & Marks ---
    def get_isa_marks(self, semester: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            if semester and semester.strip() and semester.strip().lower() not in ("all", "all semesters", "all_semesters"):
                rows = conn.execute(
                    "SELECT * FROM isa_marks WHERE LOWER(semester) = LOWER(?) ORDER BY subject_name ASC",
                    (semester.strip(),)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM isa_marks ORDER BY semester ASC, subject_name ASC").fetchall()
            return [dict(r) for r in rows]

    def upsert_isa_marks(
        self,
        subject_code: str,
        subject_name: str,
        semester: str = "",
        credits: float = 4.0,
        isa1_score: Optional[float] = None,
        isa1_max: float = 40.0,
        isa2_score: Optional[float] = None,
        isa2_max: float = 40.0,
        assignment_score: Optional[float] = None,
        assignment_max: float = 10.0,
        project_or_lab: Optional[float] = None,
        project_max: float = 10.0,
        cie_total: Optional[float] = None,
        source: str = "scraped"
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        # Calculate scaled CIE if not explicitly given or 0:
        # PESU Scheme: ISA 1 and ISA 2 total is 45 marks (22.5 each), Assignment/Lab is 5 marks (Total 50)
        if cie_total is None or cie_total == 0:
            m2 = isa2_max if (isa2_max and isa2_max > 0) else isa1_max
            c1 = (isa1_score / isa1_max * 22.5) if (isa1_score is not None and isa1_max > 0) else 0.0
            c2 = (isa2_score / m2 * 22.5) if (isa2_score is not None and m2 and m2 > 0) else 0.0
            c_isa = min(45.0, c1 + c2)

            asg_raw = assignment_score if assignment_score is not None else 0.0
            asg_m = assignment_max if assignment_max and assignment_max > 0 else 10.0
            asg_contrib = min(5.0, (asg_raw / asg_m) * 5.0)

            proj_raw = project_or_lab if project_or_lab is not None else 0.0
            proj_m = project_max if project_max and project_max > 0 else 10.0
            proj_contrib = min(5.0, (proj_raw / proj_m) * 5.0) if proj_raw > 0 else 0.0

            cie_total = round(min(50.0, c_isa + asg_contrib + proj_contrib), 2)

        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO isa_marks (
                    subject_code, subject_name, semester, credits,
                    isa1_score, isa1_max, isa2_score, isa2_max,
                    assignment_score, assignment_max, project_or_lab, project_max,
                    cie_total, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subject_code, semester) DO UPDATE SET
                    subject_name = excluded.subject_name,
                    credits = excluded.credits,
                    isa1_score = COALESCE(excluded.isa1_score, isa_marks.isa1_score),
                    isa1_max = excluded.isa1_max,
                    isa2_score = COALESCE(excluded.isa2_score, isa_marks.isa2_score),
                    isa2_max = excluded.isa2_max,
                    assignment_score = COALESCE(excluded.assignment_score, isa_marks.assignment_score),
                    assignment_max = excluded.assignment_max,
                    project_or_lab = COALESCE(excluded.project_or_lab, isa_marks.project_or_lab),
                    project_max = excluded.project_max,
                    cie_total = excluded.cie_total,
                    source = excluded.source,
                    updated_at = excluded.updated_at
            """, (
                subject_code, subject_name, semester, credits,
                isa1_score, isa1_max, isa2_score, isa2_max,
                assignment_score, assignment_max, project_or_lab, project_max,
                cie_total, source, now
            ))
            conn.commit()

    def clear_isa_marks(self, semester: Optional[str] = None) -> None:
        with self.get_connection() as conn:
            if semester and semester.strip() and semester.strip().lower() not in ("all", "all semesters"):
                conn.execute("DELETE FROM isa_marks WHERE LOWER(semester) = LOWER(?)", (semester.strip(),))
            else:
                conn.execute("DELETE FROM isa_marks")
            conn.commit()

    # --- Timetable ---
    def get_timetable(self, day_of_week: Optional[int] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            if day_of_week is not None:
                rows = conn.execute(
                    "SELECT * FROM timetable WHERE day_of_week = ? ORDER BY period_number ASC",
                    (day_of_week,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM timetable ORDER BY day_of_week ASC, period_number ASC").fetchall()
            return [dict(r) for r in rows]

    def set_timetable_entry(
        self,
        day_of_week: int,
        period_number: int,
        subject_name: str,
        subject_code: str = "",
        start_time: str = "",
        end_time: str = "",
        room: str = "",
        is_lab: bool = False
    ) -> int:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO timetable (day_of_week, period_number, start_time, end_time, subject_code, subject_name, room, is_lab)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (day_of_week, period_number, start_time, end_time, subject_code, subject_name, room, 1 if is_lab else 0))
            conn.commit()
            return cursor.lastrowid

    def clear_timetable(self) -> None:
        with self.get_connection() as conn:
            conn.execute("DELETE FROM timetable")
            conn.commit()

    # --- Assignments ---
    def get_assignments(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM assignments ORDER BY (status = 'completed') ASC, due_date ASC").fetchall()
            return [dict(r) for r in rows]

    def save_assignment(
        self,
        assignment_id: str,
        title: str,
        subject: str,
        due_date: str,
        priority: str = "medium",
        status: str = "pending",
        notes: str = ""
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO assignments (id, title, subject, due_date, priority, status, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    subject = excluded.subject,
                    due_date = excluded.due_date,
                    priority = excluded.priority,
                    status = excluded.status,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
            """, (assignment_id, title, subject, due_date, priority, status, notes, now, now))
            conn.commit()

    def update_assignment_status(self, assignment_id: str, completed: bool) -> None:
        now = datetime.now(timezone.utc).isoformat()
        status = "completed" if completed else "pending"
        with self.get_connection() as conn:
            conn.execute("UPDATE assignments SET status = ?, updated_at = ? WHERE id = ?", (status, now, assignment_id))
            conn.commit()

    def delete_assignment(self, assignment_id: str) -> None:
        with self.get_connection() as conn:
            conn.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
            conn.commit()

    # --- Bookmarks ---
    def get_bookmarks(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM bookmarks ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def add_bookmark(self, file_path: str, title: str, page_number: int = 1, notes: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO bookmarks (file_path, title, page_number, notes, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    page_number = excluded.page_number,
                    notes = excluded.notes
            """, (file_path, title, page_number, notes, now))
            conn.commit()

    def remove_bookmark(self, file_path: str) -> None:
        with self.get_connection() as conn:
            conn.execute("DELETE FROM bookmarks WHERE file_path = ?", (file_path,))
            conn.commit()

    def is_bookmarked(self, file_path: str) -> bool:
        with self.get_connection() as conn:
            row = conn.execute("SELECT 1 FROM bookmarks WHERE file_path = ?", (file_path,)).fetchone()
            return row is not None

    # --- Recent Files ---
    def record_recent_file(self, file_path: str, title: str, breadcrumb: str = "", last_page: int = 1) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO recent_files (file_path, title, breadcrumb, last_page, last_viewed_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    title = excluded.title,
                    breadcrumb = excluded.breadcrumb,
                    last_page = excluded.last_page,
                    last_viewed_at = excluded.last_viewed_at
            """, (file_path, title, breadcrumb, last_page, now))
            conn.commit()

    def get_recent_files(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM recent_files ORDER BY last_viewed_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    # --- Study Sessions & Analytics ---
    def record_study_session(
        self,
        mode: str,
        duration_seconds: int,
        subject: Optional[str] = None,
        notes: str = ""
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO study_sessions (mode, duration_seconds, subject, completed_at, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (mode, duration_seconds, subject, now, notes))
            conn.commit()
            return cursor.lastrowid

    def get_study_stats(self) -> Dict[str, Any]:
        """Aggregate total study minutes today, this week, and overall sessions."""
        with self.get_connection() as conn:
            total_sessions = conn.execute("SELECT COUNT(*) FROM study_sessions WHERE mode = 'focus'").fetchone()[0]
            total_seconds = conn.execute("SELECT COALESCE(SUM(duration_seconds), 0) FROM study_sessions WHERE mode = 'focus'").fetchone()[0]

            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_seconds = conn.execute(
                "SELECT COALESCE(SUM(duration_seconds), 0) FROM study_sessions WHERE mode = 'focus' AND completed_at LIKE ?",
                (f"{today}%",)
            ).fetchone()[0]

            # Last 7 days daily trend
            recent_rows = conn.execute("""
                SELECT substr(completed_at, 1, 10) as day, SUM(duration_seconds) as total_sec, COUNT(*) as count
                FROM study_sessions
                WHERE mode = 'focus'
                GROUP BY day
                ORDER BY day DESC
                LIMIT 7
            """).fetchall()

            # Subject breakdown
            subject_rows = conn.execute("""
                SELECT COALESCE(subject, 'General') as subj, SUM(duration_seconds) as total_sec, COUNT(*) as count
                FROM study_sessions
                WHERE mode = 'focus'
                GROUP BY subj
                ORDER BY total_sec DESC
            """).fetchall()

            return {
                "total_completed_sessions": total_sessions,
                "total_focus_minutes": round(total_seconds / 60, 1),
                "today_focus_minutes": round(today_seconds / 60, 1),
                "daily_trend": [dict(r) for r in reversed(recent_rows)],
                "subject_breakdown": [dict(r) for r in subject_rows]
            }

    # --- Settings ---
    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.get_connection() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            if not row:
                return default
            try:
                return json.loads(row["value"])
            except Exception:
                return row["value"]

    def set_setting(self, key: str, value: Any) -> None:
        encoded = json.dumps(value)
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, encoded))
            conn.commit()

    def get_all_settings(self) -> Dict[str, Any]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            out = {}
            for r in rows:
                try:
                    out[r["key"]] = json.loads(r["value"])
                except Exception:
                    out[r["key"]] = r["value"]
            return out
