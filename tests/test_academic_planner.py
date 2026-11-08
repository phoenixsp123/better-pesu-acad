"""
Tests for academic planner and grade calculator.
"""

import tempfile
from pathlib import Path
from backend.db import Database
from backend.academic.planner import AcademicPlanner
from backend.academic.grades import GradeCalculator, SubjectGrade


def test_grade_calculator_sgpa():
    # 4 subjects:
    # Math: 4 credits, Grade S (10) -> 40
    # OS: 4 credits, Grade A (9) -> 36
    # DSA: 4 credits, Grade B (8) -> 32
    # Lab: 2 credits, Grade S (10) -> 20
    # Total credits = 14. Total points = 128. SGPA = 128 / 14 = 9.14
    subjects = [
        SubjectGrade(subject_code="MA201", subject_title="Math", credits=4, grade="S"),
        SubjectGrade(subject_code="CS201", subject_title="OS", credits=4, grade="A"),
        SubjectGrade(subject_code="CS202", subject_title="DSA", credits=4, grade="B"),
        SubjectGrade(subject_code="CS203", subject_title="Lab", credits=2, grade="S"),
    ]
    sgpa = GradeCalculator.calculate_sgpa(subjects)
    assert sgpa == 9.14


def test_grade_calculator_cgpa():
    # Sem 1: 20 credits, SGPA 9.0 -> 180 points
    # Sem 2: 20 credits, SGPA 8.0 -> 160 points
    # CGPA = (180 + 160) / 40 = 8.5
    semesters = [
        {"credits": 20, "sgpa": 9.0},
        {"credits": 20, "sgpa": 8.0},
    ]
    cgpa = GradeCalculator.calculate_cgpa(semesters)
    assert cgpa == 8.5


def test_planner_assignment_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        planner = AcademicPlanner(db)

        # Create
        asg = planner.create_assignment(
            title="OS Lab 4",
            subject="Operating Systems",
            due_date="2026-12-01",
            priority="high",
            notes="IPC pipes"
        )
        assert asg["title"] == "OS Lab 4"

        # List
        items = planner.list_assignments()
        assert len(items) == 1
        assert items[0]["status"] == "pending"

        # Toggle
        planner.toggle_assignment(asg["id"], True)
        items = planner.list_assignments()
        assert items[0]["status"] == "completed"
        assert items[0]["status_label"] == "Completed"

        # Remove
        planner.remove_assignment(asg["id"])
        assert len(planner.list_assignments()) == 0
