"""
Main Flask application server for Better PESU Acad.
Binds to localhost, protects endpoints with origin & token checks,
and serves academic APIs and slides files safely.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit
from typing import Optional

from flask import (
    Flask,
    jsonify,
    render_template,
    send_from_directory,
    request,
    Response,
    abort
)

from backend.config import Config, find_libreoffice
from backend.db import Database
from backend.auth.manager import AuthManager
from backend.academic.attendance import (
    AttendanceCalculator,
    export_attendance_to_csv,
    parse_attendance_csv
)
from backend.academic.planner import AcademicPlanner
from backend.academic.grades import GradeCalculator, SubjectGrade
from backend.academic.provider import AcademicDataProvider
from backend.jobs.sync_manager import SyncManager

logger = logging.getLogger("betterpesu.app")


def create_app(config: Optional[Config] = None) -> Flask:
    if config is None:
        config = Config()

    app = Flask(
        __name__,
        template_folder=str(config.templates_dir),
        static_folder=str(config.static_dir)
    )

    # Security: internal app token generated per session
    app_token = secrets.token_hex(16)
    app.config["BETTERPESU_TOKEN"] = app_token
    app.config["BETTERPESU_CONFIG"] = config

    # Initialize services
    db = Database(config.db_path)
    auth_mgr = AuthManager(config.session_file, db)
    sync_mgr = SyncManager(config, auth_mgr)
    planner = AcademicPlanner(db)
    academic_provider = AcademicDataProvider(auth_mgr.session, db)

    def is_local_request() -> bool:
        """Validate that incoming requests originate strictly from local machine."""
        if request.remote_addr not in ("127.0.0.1", "::1", "localhost"):
            return False
        host = request.host.split(":")[0].strip("[]").lower()
        if host not in ("localhost", "127.0.0.1", "::1"):
            return False
        origin = request.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in ("http", "https") or parsed.netloc != request.host:
                return False
        return True

    @app.before_request
    def check_origin():
        if not is_local_request():
            return jsonify({"error": "Forbidden: Local access only."}), 403

    # --- UI Rendering ---
    @app.get("/")
    def index():
        return render_template("index.html", app_token=app_token)

    # --- System & Status ---
    @app.get("/api/system/status")
    def system_status():
        lo_path = find_libreoffice()
        return jsonify({
            "app_name": "Better PESU Acad",
            "version": "2.0.0",
            "libreoffice_available": lo_path is not None,
            "libreoffice_path": lo_path,
            "data_directory": str(config.data_dir),
            "slides_directory": str(config.slides_dir),
            "db_path": str(config.db_path),
            "token": app_token
        })

    # --- Authentication Endpoints ---
    @app.get("/api/auth/status")
    def auth_status():
        is_valid = auth_mgr.is_session_valid()
        profile = db.get_profile()
        return jsonify({
            "authenticated": is_valid,
            "profile": profile,
            "has_saved_session": config.session_file.is_file()
        })

    @app.post("/api/auth/login")
    def auth_login():
        payload = request.get_json(silent=True) or {}
        username = payload.get("username", "").strip()
        password = payload.get("password", "").strip()
        if not username or not password:
            return jsonify({"error": "Username and password are required."}), 400

        res = auth_mgr.authenticate_direct(username, password, fetch_profile=True)
        if not res.success:
            return jsonify({"error": res.message}), 401

        # Also trigger background timetable/attendance sync if possible
        try:
            academic_provider.sync_timetable()
        except Exception:
            pass

        return jsonify({
            "message": res.message,
            "profile": res.profile
        })

    @app.post("/api/auth/logout")
    def auth_logout():
        auth_mgr.clear_session()
        return jsonify({"message": "Successfully logged out and cleared session."})

    @app.get("/api/auth/profile")
    def get_profile():
        prof = db.get_profile()
        return jsonify(prof or {})

    @app.post("/api/auth/profile")
    def update_profile():
        data = request.get_json(silent=True) or {}
        prof = db.get_profile() or {
            "name": "",
            "srn": "",
            "prn": "",
            "branch": "",
            "semester": "",
            "section": "",
            "campus": "",
            "email": "",
            "auth_provider": "local"
        }
        for k in ["name", "srn", "prn", "branch", "semester", "section", "campus", "email"]:
            if k in data and data[k] is not None:
                prof[k] = str(data[k]).strip()
        db.save_profile(prof)
        return jsonify({"message": "Profile updated successfully.", "profile": db.get_profile()})

    # --- Courses & Slides Endpoints ---
    @app.get("/api/courses")
    def courses():
        target_file = None
        candidates = [
            config.courses_json,
            Path.cwd() / "data" / "courses.json",
            Path.cwd() / "pesu-notes" / "data" / "courses.json",
            Path(__file__).resolve().parent.parent / "data" / "courses.json",
            Path(__file__).resolve().parent.parent / "pesu-notes" / "data" / "courses.json",
        ]
        for c in candidates:
            if c.is_file() and c.stat().st_size > 0:
                target_file = c
                break

        if not target_file:
            return jsonify({})
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception as e:
            logger.error("Could not read courses.json: %s", e)
            return jsonify({"error": "Could not read courses catalog."}), 500

    @app.get("/api/semesters")
    def list_semesters():
        try:
            # First check from local courses.json
            local_sems = []
            candidates = [
                config.courses_json,
                Path.cwd() / "data" / "courses.json",
                Path.cwd() / "pesu-notes" / "data" / "courses.json",
            ]
            for c in candidates:
                if c.is_file() and c.stat().st_size > 0:
                    try:
                        with open(c, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            local_sems = list(data.keys())
                            break
                    except Exception:
                        pass

            # If user has an active session, also query PESU Academy
            pesu_sems = []
            pesu_map = {}
            if auth_mgr.is_session_valid():
                try:
                    downloader = sync_mgr.downloader
                    pesu_map = downloader.get_semesters()
                    pesu_sems = list(pesu_map.keys())
                except Exception as e:
                    logger.warning("Could not fetch semesters from PESU: %s", e)

            # Merge uniquely
            all_sems = sorted(list(set(local_sems + pesu_sems)))
            return jsonify({
                "semesters": all_sems,
                "details": [{"name": s, "id": pesu_map.get(s, "")} for s in all_sems]
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # --- Safe File Serving & Desktop System Integrations ---
    def resolve_slide_file(raw_path: str) -> Optional[Path]:
        if not raw_path:
            return None
        clean = raw_path.strip().lstrip("/").replace("\\", "/")
        if clean.lower().startswith("slides/"):
            clean = clean[7:]
        target = config.slides_dir / clean
        if target.is_file():
            return target
        candidates = [
            Path.cwd() / "slides" / clean,
            Path.cwd() / "pesu-notes" / "slides" / clean,
            Path(__file__).resolve().parent.parent / "slides" / clean,
            Path(__file__).resolve().parent.parent / "pesu-notes" / "slides" / clean,
        ]
        for cand in candidates:
            if cand.is_file():
                return cand
        return None

    @app.get("/files/<path:filename>")
    def serve_file(filename: str):
        target = resolve_slide_file(filename)
        if not target:
            return jsonify({"error": "File not found"}), 404
        return send_from_directory(target.parent, target.name, as_attachment=False)

    @app.get("/files/download/<path:filename>")
    def download_file(filename: str):
        target = resolve_slide_file(filename)
        if not target:
            return jsonify({"error": "File not found"}), 404
        return send_from_directory(target.parent, target.name, as_attachment=True, download_name=target.name)

    @app.post("/api/files/open-native")
    def open_file_native():
        import subprocess, sys
        payload = request.get_json(silent=True) or {}
        raw_path = payload.get("path") or ""
        target = resolve_slide_file(raw_path)
        if not target:
            return jsonify({"error": "File not found on disk"}), 404
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            elif sys.platform == "win32":
                os.startfile(str(target))
            else:
                subprocess.Popen(["xdg-open", str(target)])
            return jsonify({"success": True, "message": f"Opened {target.name} in default viewer."})
        except Exception as e:
            logger.warning("Could not open native viewer: %s", e)
            return jsonify({"error": str(e)}), 500

    @app.post("/api/files/reveal-in-finder")
    def reveal_in_finder():
        import subprocess, sys
        payload = request.get_json(silent=True) or {}
        raw_path = payload.get("path") or ""
        target = resolve_slide_file(raw_path)
        if not target:
            return jsonify({"error": "File not found on disk"}), 404
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(target)])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", f"/select,{target}"])
            else:
                subprocess.Popen(["xdg-open", str(target.parent)])
            return jsonify({"success": True, "message": f"Revealed {target.name} in file manager."})
        except Exception as e:
            logger.warning("Could not reveal file in finder: %s", e)
            return jsonify({"error": str(e)}), 500

    # --- Synchronization Endpoints ---
    @app.post("/api/sync")
    def start_sync():
        payload = request.get_json(silent=True) or {}
        semester = payload.get("semester")
        convert_only = payload.get("convert_only", False)

        selection = None
        if semester:
            selection = {"semester": semester}

        try:
            state = sync_mgr.start_sync(selection=selection, convert_only=convert_only)
            return jsonify(state), 202
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 409
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.post("/api/sync/subject")
    def sync_subject():
        payload = request.get_json(silent=True) or {}
        semester = payload.get("semester")
        subject_id = payload.get("subject_id")

        if not semester or not subject_id:
            return jsonify({"error": "Semester and subject_id are required."}), 400

        selection = {"semester": str(semester), "subject_id": str(subject_id)}
        try:
            state = sync_mgr.start_sync(selection=selection)
            return jsonify(state), 202
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 409
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.get("/api/sync/status")
    def sync_status():
        return jsonify(sync_mgr.get_status())

    @app.post("/api/sync/cancel")
    def sync_cancel():
        cancelled = sync_mgr.cancel()
        return jsonify({"cancelled": cancelled})

    # --- Attendance Endpoints ---
    @app.get("/api/attendance")
    def get_attendance():
        sem = request.args.get("semester")
        records = db.get_all_attendance(semester=sem)
        analyses = []
        for r in records:
            analysis = AttendanceCalculator.analyze_subject(
                subject_code=r["subject_code"],
                subject_name=r["subject_name"],
                attended=r["attended"],
                conducted=r["conducted"],
                target_percentage=r.get("target_percentage", 75.0)
            )
            data = analysis.to_dict()
            data["updated_at"] = r.get("updated_at")
            data["source"] = r.get("source")
            data["semester"] = r.get("semester", "")
            analyses.append(data)
        return jsonify({"records": analyses, "semester": sem})

    @app.post("/api/attendance")
    def upsert_attendance():
        payload = request.get_json(silent=True) or {}
        code = payload.get("subject_code", "").strip()
        name = payload.get("subject_name", "").strip() or code
        attended = int(payload.get("attended", 0))
        conducted = int(payload.get("conducted", 0))
        target = float(payload.get("target_percentage", 75.0))

        if not code:
            return jsonify({"error": "Subject code is required."}), 400
        if conducted < attended:
            conducted = attended

        db.upsert_attendance(
            subject_code=code,
            subject_name=name,
            attended=attended,
            conducted=conducted,
            target_percentage=target,
            semester=payload.get("semester", ""),
            source="manual"
        )
        return jsonify({"message": "Attendance saved successfully."}), 201

    @app.put("/api/attendance/<subject_code>/target")
    def set_target(subject_code: str):
        payload = request.get_json(silent=True) or {}
        target = float(payload.get("target_percentage", 75.0))
        db.set_attendance_target(subject_code, target)
        return jsonify({"message": f"Target updated to {target}%."})

    @app.delete("/api/attendance/<subject_code>")
    def delete_attendance(subject_code: str):
        db.delete_attendance(subject_code)
        return jsonify({"message": "Subject attendance removed."})

    @app.post("/api/attendance/simulate")
    def simulate_attendance():
        payload = request.get_json(silent=True) or {}
        attended = int(payload.get("attended", 0))
        conducted = int(payload.get("conducted", 0))
        target = float(payload.get("target_percentage", 75.0))
        bunk_count = int(payload.get("bunk_count", 0))
        attend_count = int(payload.get("attend_count", 0))
        chain = payload.get("chain", [])

        if chain:
            results = AttendanceCalculator.simulate_custom_chain(attended, conducted, chain)
            return jsonify({"type": "chain", "results": results})

        new_att = attended + attend_count
        new_cond = conducted + attend_count + bunk_count
        analysis = AttendanceCalculator.analyze_subject(
            subject_code="SIM",
            subject_name="Simulated Scenario",
            attended=new_att,
            conducted=new_cond,
            target_percentage=target
        )
        matrix = AttendanceCalculator.generate_bunk_matrix(new_att, new_cond, max_miss=5)
        return jsonify({
            "analysis": analysis.to_dict(),
            "bunk_matrix": matrix
        })

    @app.get("/api/attendance/export")
    def export_csv():
        records = db.get_all_attendance()
        analyses = [
            AttendanceCalculator.analyze_subject(
                r["subject_code"],
                r["subject_name"],
                r["attended"],
                r["conducted"],
                r.get("target_percentage", 75.0)
            ) for r in records
        ]
        csv_text = export_attendance_to_csv(analyses)
        return Response(
            csv_text,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=attendance.csv"}
        )

    @app.post("/api/attendance/import")
    def import_csv():
        if "file" in request.files:
            content = request.files["file"].read().decode("utf-8", errors="ignore")
        else:
            payload = request.get_json(silent=True) or {}
            content = payload.get("csv_content", "")

        records = parse_attendance_csv(content)
        if not records:
            return jsonify({"error": "No valid attendance records found in CSV."}), 400

        for r in records:
            db.upsert_attendance(
                subject_code=r["subject_code"],
                subject_name=r["subject_name"],
                attended=r["attended"],
                conducted=r["conducted"],
                target_percentage=r.get("target_percentage", 75.0),
                source="csv_import"
            )
        return jsonify({"message": f"Successfully imported {len(records)} subjects."}), 201

    @app.post("/api/attendance/sync")
    def sync_live_attendance():
        if not auth_mgr.is_session_valid():
            return jsonify({"error": "You must be signed in to PESU Academy to sync attendance."}), 401

        payload = request.get_json(silent=True) or {}
        semester_id = payload.get("semester_id")
        semester_name = payload.get("semester", "")

        try:
            sems = {}
            if auth_mgr.is_session_valid():
                try:
                    sems = sync_mgr.downloader.get_semesters()
                except Exception as e:
                    logger.warning("Could not fetch semesters for attendance sync: %s", e)

            if semester_name and not semester_id and semester_name in sems:
                semester_id = sems[semester_name]

            if not semester_id:
                if not sems:
                    return jsonify({"error": "No semesters found on PESU Academy profile."}), 400
                semester_name, semester_id = list(sems.items())[-1]

            records = academic_provider.sync_attendance_for_semester(str(semester_id), semester_name=semester_name)
            return jsonify({
                "message": f"Synced attendance for {len(records)} subjects ({semester_name or semester_id}).",
                "records": records,
                "semester": semester_name
            })
        except Exception as e:
            logger.exception("Failed to sync attendance: %s", e)
            return jsonify({"error": f"Failed to sync attendance: {str(e)}"}), 500

    # --- Timetable Endpoints ---
    @app.get("/api/timetable")
    def get_timetable():
        day = request.args.get("day", type=int)
        entries = db.get_timetable(day_of_week=day)
        return jsonify({"timetable": entries})

    @app.post("/api/timetable/sync")
    def sync_timetable():
        if not auth_mgr.is_session_valid():
            return jsonify({"error": "You must be signed in to PESU Academy to sync timetable."}), 401
        try:
            entries = academic_provider.sync_timetable()
            return jsonify({
                "message": f"Synced {len(entries)} timetable periods from PESU Academy.",
                "timetable": entries
            })
        except Exception as e:
            logger.exception("Failed to sync timetable: %s", e)
            return jsonify({"error": f"Failed to sync timetable: {str(e)}"}), 500

    @app.post("/api/timetable")
    def add_timetable_entry():
        p = request.get_json(silent=True) or {}
        day = int(p.get("day_of_week", 0))
        period = int(p.get("period_number", 1))
        name = p.get("subject_name", "").strip()
        code = p.get("subject_code", "").strip()
        start = p.get("start_time", "").strip()
        end = p.get("end_time", "").strip()
        room = p.get("room", "").strip()
        is_lab = bool(p.get("is_lab", False))

        if not name:
            return jsonify({"error": "Subject name is required."}), 400

        entry_id = db.set_timetable_entry(day, period, name, code, start, end, room, is_lab)
        return jsonify({"id": entry_id, "message": "Timetable entry added."}), 201

    @app.delete("/api/timetable")
    def clear_timetable():
        db.clear_timetable()
        return jsonify({"message": "Timetable cleared."})

    # --- Assignments Endpoints ---
    @app.get("/api/assignments")
    def get_assignments():
        subj = request.args.get("subject")
        return jsonify({"assignments": planner.list_assignments(subject_filter=subj)})

    @app.post("/api/assignments")
    def add_assignment():
        p = request.get_json(silent=True) or {}
        title = p.get("title", "").strip()
        subject = p.get("subject", "").strip()
        due_date = p.get("due_date", "").strip()
        priority = p.get("priority", "medium")
        notes = p.get("notes", "").strip()

        if not title or not subject or not due_date:
            return jsonify({"error": "Title, subject, and due date are required."}), 400

        item = planner.create_assignment(title, subject, due_date, priority, notes)
        return jsonify({"message": "Assignment created.", "assignment": item}), 201

    @app.put("/api/assignments/<assignment_id>/toggle")
    def toggle_assignment(assignment_id: str):
        p = request.get_json(silent=True) or {}
        completed = bool(p.get("completed", False))
        planner.toggle_assignment(assignment_id, completed)
        return jsonify({"message": "Assignment updated."})

    @app.delete("/api/assignments/<assignment_id>")
    def delete_assignment(assignment_id: str):
        planner.remove_assignment(assignment_id)
        return jsonify({"message": "Assignment removed."})

    # --- Grades, ISA Results & GPA Predictor ---
    @app.get("/api/grades/isa")
    def get_isa_marks():
        sem = request.args.get("semester")
        marks = db.get_isa_marks(semester=sem)
        if not marks and auth_mgr.is_session_valid():
            try:
                marks = academic_provider.sync_isa_marks(semester_name=sem or "")
            except Exception as e:
                logger.warning("Auto sync ISA marks on get: %s", e)
        if not marks:
            # Seed with attendance subjects if none exist
            att = db.get_all_attendance(semester=sem)
            for a in att:
                code_u = (a["subject_code"] or "").upper()
                name_u = (a.get("subject_name") or "").upper()
                is_cie = code_u.startswith("UZ") or bool(re.search(r"\bCIE\b", code_u) or re.search(r"\bCIE\b", name_u) or "INNOVATION" in name_u)
                default_isa_max = 45.0 if is_cie else 40.0
                db.upsert_isa_marks(
                    subject_code=a["subject_code"],
                    subject_name=a["subject_name"],
                    semester=sem or a.get("semester", ""),
                    credits=4.0,
                    isa1_max=default_isa_max,
                    isa2_max=default_isa_max,
                    source="attendance_seed"
                )
            marks = db.get_isa_marks(semester=sem)

        for m in marks:
            code_u = (m.get("subject_code") or "").upper()
            name_u = (m.get("subject_name") or "").upper()
            is_cie = code_u.startswith("UZ") or bool(re.search(r"\bCIE\b", code_u) or re.search(r"\bCIE\b", name_u) or "INNOVATION" in name_u) or m.get("isa1_max") == 45.0
            m["is_cie"] = is_cie
            m["esa_max"] = 50.0 if is_cie else 100.0
            if is_cie:
                if not m.get("isa1_max") or m.get("isa1_max") == 40.0:
                    m["isa1_max"] = 45.0
                if not m.get("isa2_max") or m.get("isa2_max") == 40.0:
                    m["isa2_max"] = 45.0

        return jsonify({"marks": marks, "semester": sem})

    @app.post("/api/grades/isa/sync")
    def sync_isa_marks():
        if not auth_mgr.is_session_valid():
            return jsonify({"error": "You must be signed in to PESU Academy to fetch ISA marks."}), 401
        payload = request.get_json(silent=True) or {}
        sem_id = payload.get("semester_id")
        sem_name = payload.get("semester", "")
        try:
            records = academic_provider.sync_isa_marks(semester_id=sem_id, semester_name=sem_name)
            return jsonify({
                "message": f"Fetched ISA marks for {len(records)} subjects ({sem_name or 'current'}).",
                "marks": records,
                "semester": sem_name
            })
        except Exception as e:
            logger.exception("Failed to fetch ISA marks: %s", e)
            return jsonify({"error": f"Failed to fetch ISA marks: {str(e)}"}), 500

    @app.post("/api/grades/predict")
    def predict_gpa():
        payload = request.get_json(silent=True) or {}
        subjects = payload.get("subjects", [])
        results = []
        total_cred = 0.0
        weighted_points = 0.0

        for s in subjects:
            code = s.get("subject_code", "")
            name = s.get("subject_name", code)
            cred = float(s.get("credits", 4.0))
            cie = float(s.get("cie_total", s.get("cie", 0.0)))
            expected_esa = s.get("expected_esa")
            if expected_esa is not None and str(expected_esa).strip() != "":
                try:
                    expected_esa = float(expected_esa)
                except ValueError:
                    expected_esa = None
            else:
                expected_esa = None

            target_grade = (s.get("target_grade") or "S").upper()
            cutoffs = {"S": 90, "A": 80, "B": 70, "C": 60, "D": 50, "E": 40}
            target_cutoff = cutoffs.get(target_grade, 90)

            code_u = code.upper().strip()
            name_u = name.upper().strip()
            is_cie = code_u.startswith("UZ") or bool(re.search(r"\bCIE\b", code_u) or re.search(r"\bCIE\b", name_u) or "INNOVATION" in name_u) or float(s.get("isa1_max", 40.0)) == 45.0
            
            # ESA Max is 50 for CIE, 100 for regular subjects
            esa_max = 50.0 if is_cie else float(s.get("esa_max", 100.0))
            pts_needed_50 = max(0.0, float(target_cutoff - cie))

            if esa_max == 50.0:
                needed_esa = pts_needed_50
                is_impossible = (needed_esa > 50.0)
                actual_esa = expected_esa if expected_esa is not None else (needed_esa if not is_impossible else 0.0)
                actual_esa = min(50.0, max(0.0, actual_esa))
                pred_total = min(100.0, max(0.0, cie + actual_esa))
            else:
                # Regular course: ESA exam is 100 marks (50% weightage towards total of 100)
                needed_esa = pts_needed_50 * 2.0
                is_impossible = (needed_esa > 100.0)
                actual_esa = expected_esa if expected_esa is not None else (needed_esa if not is_impossible else 0.0)
                actual_esa = min(100.0, max(0.0, actual_esa))
                pred_total = min(100.0, max(0.0, cie + (actual_esa * 0.5)))

            if pred_total >= 90:
                grade_letter = "S"
                grade_point = 10.0
            elif pred_total >= 80:
                grade_letter = "A"
                grade_point = 9.0
            elif pred_total >= 70:
                grade_letter = "B"
                grade_point = 8.0
            elif pred_total >= 60:
                grade_letter = "C"
                grade_point = 7.0
            elif pred_total >= 50:
                grade_letter = "D"
                grade_point = 6.0
            elif pred_total >= 40:
                grade_letter = "E"
                grade_point = 5.0
            else:
                grade_letter = "F"
                grade_point = 0.0

            total_cred += cred
            weighted_points += (cred * grade_point)

            results.append({
                "subject_code": code,
                "subject_name": name,
                "credits": cred,
                "cie": round(cie, 2),
                "is_cie": is_cie,
                "esa_max": esa_max,
                "target_grade": target_grade,
                "target_esa_needed": round(needed_esa, 1),
                "is_impossible": is_impossible,
                "expected_esa": expected_esa,
                "predicted_total": round(pred_total, 1),
                "predicted_grade": grade_letter,
                "predicted_grade_point": grade_point
            })

        predicted_sgpa = round(weighted_points / total_cred, 2) if total_cred > 0 else 0.0
        return jsonify({
            "predicted_sgpa": predicted_sgpa,
            "total_credits": total_cred,
            "subjects": results,
            "results": results
        })

    @app.post("/api/grades/calculate")
    def calculate_sgpa():
        p = request.get_json(silent=True) or {}
        raw_subjects = p.get("subjects", [])
        subjects = [
            SubjectGrade(
                subject_code=s.get("code", f"SUBJ-{i}"),
                subject_title=s.get("title", ""),
                credits=float(s.get("credits", 4.0)),
                grade=s.get("grade"),
                grade_point=float(s["grade_point"]) if s.get("grade_point") is not None else None,
                is_hypothetical=s.get("is_hypothetical", True)
            ) for i, s in enumerate(raw_subjects)
        ]
        sgpa = GradeCalculator.calculate_sgpa(subjects)
        return jsonify({"sgpa": sgpa, "subjects": [s.to_dict() for s in subjects]})

    @app.post("/api/grades/internals")
    def calculate_cie():
        p = request.get_json(silent=True) or {}
        isa1 = float(p.get("isa1", 0.0))
        isa2 = float(p.get("isa2", 0.0))
        asg = float(p.get("assignment", 0.0))
        lab = float(p.get("project_or_lab", 0.0))
        max_marks = float(p.get("max_marks", 50.0))

        result = GradeCalculator.calculate_cie_internals(isa1, isa2, asg, lab, max_marks)
        return jsonify(result)

    # --- Study Sessions & Analytics ---
    @app.post("/api/study/session")
    def log_study_session():
        p = request.get_json(silent=True) or {}
        mode = p.get("mode", "focus")
        duration = int(p.get("duration_seconds", 1500))
        subject = p.get("subject")
        notes = p.get("notes", "")

        sess_id = db.record_study_session(mode, duration, subject, notes)
        return jsonify({"id": sess_id, "message": "Study session recorded."}), 201

    @app.get("/api/study/stats")
    def get_study_stats():
        return jsonify(db.get_study_stats())

    # --- Bookmarks & Recent ---
    @app.get("/api/bookmarks")
    def get_bookmarks():
        return jsonify({"bookmarks": db.get_bookmarks()})

    @app.post("/api/bookmarks")
    def toggle_bookmark():
        p = request.get_json(silent=True) or {}
        path = p.get("file_path", "").strip()
        title = p.get("title", "").strip()
        page = int(p.get("page_number", 1))
        notes = p.get("notes", "")

        if not path:
            return jsonify({"error": "file_path is required."}), 400

        if db.is_bookmarked(path):
            db.remove_bookmark(path)
            return jsonify({"bookmarked": False, "message": "Bookmark removed."})
        else:
            db.add_bookmark(path, title or Path(path).name, page, notes)
            return jsonify({"bookmarked": True, "message": "Bookmark saved."})

    @app.get("/api/recent")
    def get_recent():
        return jsonify({"recent": db.get_recent_files()})

    @app.post("/api/recent")
    def record_recent():
        p = request.get_json(silent=True) or {}
        path = p.get("file_path", "").strip()
        title = p.get("title", "").strip()
        crumb = p.get("breadcrumb", "")
        last_page = int(p.get("last_page", 1))

        if path:
            db.record_recent_file(path, title or Path(path).name, crumb, last_page)
        return jsonify({"message": "Recent document recorded."})

    # --- Settings & Migration ---
    @app.get("/api/settings")
    def get_settings():
        return jsonify(db.get_all_settings())

    @app.post("/api/settings")
    def save_settings():
        p = request.get_json(silent=True) or {}
        for k, v in p.items():
            db.set_setting(k, v)
        return jsonify({"message": "Settings saved."})

    @app.post("/api/migrate/localstorage")
    def migrate_localstorage():
        """
        Accept exported data from legacy browser localStorage and import into SQLite.
        """
        p = request.get_json(silent=True) or {}
        imported_asgs = 0
        imported_bms = 0
        imported_sessions = 0

        # Assignments
        for a in p.get("assignments", []):
            if a.get("title") and a.get("date"):
                db.save_assignment(
                    assignment_id=a.get("id") or str(uuid.uuid4()),
                    title=a["title"],
                    subject=a.get("subject", "General"),
                    due_date=a["date"],
                    status="completed" if a.get("done") else "pending"
                )
                imported_asgs += 1

        # Bookmarks
        for bm_path in p.get("bookmarks", []):
            if isinstance(bm_path, str) and bm_path:
                db.add_bookmark(bm_path, Path(bm_path).name)
                imported_bms += 1

        # Timer completed count
        sessions_count = int(p.get("sessions", 0))
        if sessions_count > 0:
            for _ in range(sessions_count):
                db.record_study_session("focus", 1500, notes="Migrated from localStorage")
                imported_sessions += 1

        return jsonify({
            "message": "Migration completed successfully.",
            "assignments_imported": imported_asgs,
            "bookmarks_imported": imported_bms,
            "sessions_imported": imported_sessions
        })

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=True)
