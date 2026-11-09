"""
Integration tests for backend Flask application APIs and file serving security.
"""

import json
import tempfile
from pathlib import Path
import pytest

from backend.config import Config
from backend.app import create_app


@pytest.fixture
def test_client():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        cfg = Config(data_dir=tmp_path)
        # Create a sample slide for testing
        test_slide = cfg.slides_dir / "test.pdf"
        test_slide.write_bytes(b"%PDF-1.4 test pdf content")

        app = create_app(cfg)
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client, cfg


def test_system_status_endpoint(test_client):
    client, cfg = test_client
    res = client.get("/api/system/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["app_name"] == "Better PESU Acad"
    assert "libreoffice_available" in data
    assert "token" in data


def test_auth_status_initial(test_client):
    client, cfg = test_client
    res = client.get("/api/auth/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["authenticated"] is False


def test_attendance_crud_endpoints(test_client):
    client, cfg = test_client

    # Insert manual attendance
    post_res = client.post("/api/attendance", json={
        "subject_code": "UE25CS242A",
        "subject_name": "Operating System",
        "attended": 32,
        "conducted": 40,
        "target_percentage": 75.0
    })
    assert post_res.status_code == 201

    # Get attendance
    get_res = client.get("/api/attendance")
    assert get_res.status_code == 200
    records = get_res.get_json()["records"]
    assert len(records) == 1
    assert records[0]["subject_code"] == "UE25CS242A"
    assert records[0]["current_percentage"] == 80.0
    assert records[0]["classes_can_bunk"] == 2  # 32 / 0.75 - 40 = 42.66 - 40 = 2.66 -> 2
    assert records[0]["status"] == "warning"

    # Simulation endpoint
    sim_res = client.post("/api/attendance/simulate", json={
        "attended": 30,
        "conducted": 40,
        "target_percentage": 75.0,
        "bunk_count": 2
    })
    assert sim_res.status_code == 200
    sim_data = sim_res.get_json()
    # 30 / (40 + 2) = 30 / 42 = 71.43%
    assert sim_data["analysis"]["current_percentage"] == 71.43


def test_assignments_endpoints(test_client):
    client, cfg = test_client

    # Create assignment
    asg_res = client.post("/api/assignments", json={
        "title": "OS Project 1",
        "subject": "Operating System",
        "due_date": "2026-11-20",
        "priority": "high",
        "notes": "Threads and Locks"
    })
    assert asg_res.status_code == 201
    asg_id = asg_res.get_json()["assignment"]["id"]

    # List assignments
    list_res = client.get("/api/assignments")
    assert list_res.status_code == 200
    items = list_res.get_json()["assignments"]
    assert len(items) == 1
    assert items[0]["id"] == asg_id

    # Toggle assignment
    tog_res = client.put(f"/api/assignments/{asg_id}/toggle", json={"completed": True})
    assert tog_res.status_code == 200

    # Delete assignment
    del_res = client.delete(f"/api/assignments/{asg_id}")
    assert del_res.status_code == 200
    assert len(client.get("/api/assignments").get_json()["assignments"]) == 0


def test_safe_file_serving_and_traversal_prevention(test_client):
    client, cfg = test_client

    # 1. Serving valid slide
    res = client.get("/files/test.pdf")
    assert res.status_code == 200
    assert res.data == b"%PDF-1.4 test pdf content"

    # 2. Path traversal attack blocked
    traversal_res = client.get("/files/../../../../etc/passwd")
    assert traversal_res.status_code in (404, 400, 403)


def test_attendance_semester_filtering(test_client):
    client, cfg = test_client

    client.post("/api/attendance", json={
        "subject_code": "UE25CS201",
        "subject_name": "Subject Sem 3",
        "attended": 20,
        "conducted": 25,
        "target_percentage": 75.0,
        "semester": "Sem-3"
    })
    client.post("/api/attendance", json={
        "subject_code": "UE25CS101",
        "subject_name": "Subject Sem 1",
        "attended": 18,
        "conducted": 20,
        "target_percentage": 75.0,
        "semester": "Sem-1"
    })

    # All attendance
    all_res = client.get("/api/attendance")
    assert len(all_res.get_json()["records"]) == 2

    # Filtered by Sem-3
    s3_res = client.get("/api/attendance?semester=Sem-3")
    s3_records = s3_res.get_json()["records"]
    assert len(s3_records) == 1
    assert s3_records[0]["subject_code"] == "UE25CS201"

    # Filtered by Sem-1
    s1_res = client.get("/api/attendance?semester=Sem-1")
    s1_records = s1_res.get_json()["records"]
    assert len(s1_records) == 1
    assert s1_records[0]["subject_code"] == "UE25CS101"


def test_gpa_predictor_and_isa_endpoints(test_client):
    client, cfg = test_client

    # Predict GPA:
    # Regular subjects: ESA is out of 100 (50% weightage towards total of 100)
    # CIE subject: ESA is out of 50
    payload = {
        "subjects": [
            {
                "subject_code": "UE25CS252A",
                "subject_name": "Data Structures",
                "credits": 4,
                "cie_total": 42.0,
                "target_grade": "S",
                "expected_esa": 96.0  # 42 + (96*0.5) = 90.0 -> S (10)
            },
            {
                "subject_code": "UE25CS242A",
                "subject_name": "Operating Systems",
                "credits": 4,
                "cie_total": 38.0,
                "target_grade": "A",
                "expected_esa": 84.0  # 38 + (84*0.5) = 80.0 -> A (9)
            }
        ]
    }
    pred_res = client.post("/api/grades/predict", json=payload)
    assert pred_res.status_code == 200
    data = pred_res.get_json()
    assert data["predicted_sgpa"] == 9.5  # (4*10 + 4*9) / 8 = 76 / 8 = 9.5
    assert data["total_credits"] == 8.0
    assert len(data["results"]) == 2
    assert data["results"][0]["predicted_grade"] == "S"
    assert data["results"][0]["esa_max"] == 100.0
    assert data["results"][1]["predicted_grade"] == "A"
    assert data["results"][1]["esa_max"] == 100.0

    # Also test CIE exam (ESA out of 50)
    cie_res = client.post("/api/grades/predict", json={
        "subjects": [
            {
                "subject_code": "UZ25UZ221A",
                "subject_name": "CIE Essentials of Innovation",
                "credits": 4,
                "cie_total": 42.0,
                "target_grade": "S",
                "expected_esa": 48.0  # 42 + 48 = 90.0 -> S (10)
            }
        ]
    })
    assert cie_res.status_code == 200
    cie_data = cie_res.get_json()
    assert cie_data["results"][0]["esa_max"] == 50.0
    assert cie_data["results"][0]["predicted_grade"] == "S"

    # ISA marks endpoint
    isa_res = client.get("/api/grades/isa")
    assert isa_res.status_code == 200
    assert "marks" in isa_res.get_json()


def test_timetable_sync_unauthenticated(test_client):
    client, cfg = test_client
    sync_res = client.post("/api/timetable/sync")
    assert sync_res.status_code == 401


def test_file_serving_and_actions(test_client):
    client, cfg = test_client
    # Create sample slide PDF in slides_dir
    slide_file = cfg.slides_dir / "Sem-3" / "OS" / "sample.pdf"
    slide_file.parent.mkdir(parents=True, exist_ok=True)
    slide_file.write_bytes(b"%PDF-1.4 sample content")

    # Serve file
    res = client.get("/files/Sem-3/OS/sample.pdf")
    assert res.status_code == 200
    assert res.headers.get("Content-Type") == "application/pdf"

    # Download file (as_attachment=True)
    res_dl = client.get("/files/download/Sem-3/OS/sample.pdf")
    assert res_dl.status_code == 200
    assert "attachment" in res_dl.headers.get("Content-Disposition", "")

    # Open native (file exists)
    res_open = client.post("/api/files/open-native", json={"path": "Sem-3/OS/sample.pdf"})
    assert res_open.status_code == 200
    assert res_open.get_json()["success"] is True

    # Reveal in finder (file exists)
    res_rev = client.post("/api/files/reveal-in-finder", json={"path": "Sem-3/OS/sample.pdf"})
    assert res_rev.status_code == 200
    assert res_rev.get_json()["success"] is True

    # Nonexistent file handling
    res_non = client.post("/api/files/open-native", json={"path": "Sem-3/OS/nonexistent.pdf"})
    assert res_non.status_code == 404

    # PDF page count endpoint
    res_pages = client.get("/api/files/pages?path=Sem-3/OS/sample.pdf")
    assert res_pages.status_code == 200
    assert "pages" in res_pages.get_json()
    assert res_pages.get_json()["pages"] >= 1

    # Merge units endpoint
    res_merge = client.post("/api/slides/merge-units")
    assert res_merge.status_code == 200
    assert "units_processed" in res_merge.get_json()


def test_profile_update_and_resolution(test_client):
    client, cfg = test_client
    # Save a profile with "SRN : " prefix and missing semester/branch
    client.post("/api/auth/profile", json={
        "name": "pes1ug25cs468",
        "srn": "SRN : PES1UG25CS468",
        "prn": ""
    })

    # Retrieve profile - should auto-clean SRN, infer branch, infer campus, infer semester
    get_res = client.get("/api/auth/profile")
    assert get_res.status_code == 200
    p = get_res.get_json()
    assert p["srn"] == "PES1UG25CS468"
    assert p["branch"] == "Computer Science and Engineering"
    assert p["campus"] == "PES University (Ring Road)"
    assert p["semester"] == "Sem-3"

    # User updates their PRN
    update_res = client.post("/api/auth/profile", json={"prn": "PES1202300468"})
    assert update_res.status_code == 200
    p2 = update_res.get_json()["profile"]
    assert p2["prn"] == "PES1202300468"


