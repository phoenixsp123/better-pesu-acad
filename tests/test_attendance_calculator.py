"""
Unit tests for attendance formulas and edge cases.
"""

import pytest
from backend.academic.attendance import (
    AttendanceCalculator,
    export_attendance_to_csv,
    parse_attendance_csv
)


def test_basic_percentage_calculation():
    # 30 / 40 = 75.0%
    assert AttendanceCalculator.calculate_current_percentage(30, 40) == 75.0
    # 0 / 10 = 0.0%
    assert AttendanceCalculator.calculate_current_percentage(0, 10) == 0.0
    # 20 / 20 = 100.0%
    assert AttendanceCalculator.calculate_current_percentage(20, 20) == 100.0
    # 0 conducted (no classes yet) = 100.0% default
    assert AttendanceCalculator.calculate_current_percentage(0, 0) == 100.0


def test_classes_can_bunk():
    # 35 attended out of 40 conducted. Target 75%.
    # 35 / 0.75 - 40 = 46.666 - 40 = 6.666 -> floor = 6 classes can bunk.
    # Verification: If bunk 6: 35 / (40 + 6) = 35 / 46 = 76.08% >= 75%
    # If bunk 7: 35 / (40 + 7) = 35 / 47 = 74.46% < 75%
    assert AttendanceCalculator.classes_can_bunk_retaining_target(35, 40, 75.0) == 6

    # Already below target: 20 / 40 = 50% < 75% -> 0 classes can bunk
    assert AttendanceCalculator.classes_can_bunk_retaining_target(20, 40, 75.0) == 0

    # Exactly at target: 30 / 40 = 75% -> floor(30/0.75 - 40) = 40 - 40 = 0
    assert AttendanceCalculator.classes_can_bunk_retaining_target(30, 40, 75.0) == 0

    # Target 85%: 38 / 40 = 95%. 38 / 0.85 - 40 = 44.7 - 40 = 4.7 -> 4 classes
    assert AttendanceCalculator.classes_can_bunk_retaining_target(38, 40, 85.0) == 4


def test_classes_needed_to_reach_target():
    # 25 attended out of 40 conducted = 62.5%. Target 75%.
    # (0.75 * 40 - 25) / (1 - 0.75) = (30 - 25) / 0.25 = 5 / 0.25 = 20 classes.
    # Check: (25 + 20) / (40 + 20) = 45 / 60 = 75.0%
    needed, impossible = AttendanceCalculator.classes_needed_to_reach_target(25, 40, 75.0)
    assert needed == 20
    assert not impossible

    # Already above target: 35 / 40 = 87.5% >= 75% -> 0 classes needed
    needed, impossible = AttendanceCalculator.classes_needed_to_reach_target(35, 40, 75.0)
    assert needed == 0
    assert not impossible

    # Target 100% when 1 class was missed (19/20)
    # Impossible to reach 100% once missed
    needed, impossible = AttendanceCalculator.classes_needed_to_reach_target(19, 20, 100.0)
    assert needed is None
    assert impossible

    # Target 100% when 0 classes missed (20/20)
    needed, impossible = AttendanceCalculator.classes_needed_to_reach_target(20, 20, 100.0)
    assert needed == 0
    assert not impossible


def test_bunk_matrix():
    matrix = AttendanceCalculator.generate_bunk_matrix(30, 40, max_miss=3)
    assert len(matrix) == 3
    # Miss 1: 30 / 41 = 73.17%
    assert matrix[0]["miss_count"] == 1
    assert matrix[0]["projected_percentage"] == 73.17
    # Miss 2: 30 / 42 = 71.43%
    assert matrix[1]["miss_count"] == 2
    assert matrix[1]["projected_percentage"] == 71.43


def test_simulate_custom_chain():
    # Start with 10 / 10 = 100%
    # Step 1: bunk -> 10 / 11 = 90.91%
    # Step 2: attend -> 11 / 12 = 91.67%
    chain = AttendanceCalculator.simulate_custom_chain(10, 10, ["bunk", "attend"])
    assert len(chain) == 3
    assert chain[0]["percentage"] == 100.0
    assert chain[1]["attended"] == 10 and chain[1]["conducted"] == 11
    assert chain[2]["attended"] == 11 and chain[2]["conducted"] == 12


def test_csv_export_and_import():
    analyses = [
        AttendanceCalculator.analyze_subject("CS101", "Algorithms", 35, 40, 75.0),
        AttendanceCalculator.analyze_subject("CS102", "Systems", 20, 40, 75.0),
    ]
    csv_str = export_attendance_to_csv(analyses)
    assert "CS101" in csv_str
    assert "Algorithms" in csv_str

    parsed = parse_attendance_csv(csv_str)
    assert len(parsed) == 2
    assert parsed[0]["subject_code"] == "CS101"
    assert parsed[0]["attended"] == 35
    assert parsed[0]["conducted"] == 40
    assert parsed[1]["subject_code"] == "CS102"
    assert parsed[1]["attended"] == 20
