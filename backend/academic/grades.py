"""
Academic Performance and Grade Calculation module for Better PESU Acad.
Calculates SGPA, CGPA, and CIE internal assessments.
Strictly distinguishes official records from user-entered hypothetical grades.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

# PES University 10-point Grading Scale (Standard Autonomous Reference)
GRADE_POINTS = {
    "S": 10.0,
    "A": 9.0,
    "B": 8.0,
    "C": 7.0,
    "D": 6.0,
    "E": 5.0,
    "F": 0.0
}


@dataclass
class SubjectGrade:
    subject_code: str
    subject_title: str
    credits: float
    grade: Optional[str] = None
    grade_point: Optional[float] = None
    is_hypothetical: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GradeCalculator:
    """
    Computes SGPA and CGPA based on credits and grade points.
    """

    @staticmethod
    def calculate_sgpa(subjects: List[SubjectGrade]) -> Optional[float]:
        """
        SGPA = Sum(Credits * Grade Points) / Sum(Credits)
        """
        total_credits = 0.0
        weighted_points = 0.0

        for s in subjects:
            gp = s.grade_point
            if gp is None and s.grade in GRADE_POINTS:
                gp = GRADE_POINTS[s.grade]
            if gp is not None and s.credits > 0:
                total_credits += s.credits
                weighted_points += s.credits * gp

        if total_credits <= 0:
            return None
        return round(weighted_points / total_credits, 2)

    @staticmethod
    def calculate_cgpa(semester_sgpas: List[Dict[str, float]]) -> Optional[float]:
        """
        CGPA = Sum(Semester Credits * Semester SGPA) / Sum(Total Credits)
        Accepts list of {"credits": 24, "sgpa": 8.75}
        """
        total_credits = 0.0
        total_points = 0.0

        for sem in semester_sgpas:
            cr = sem.get("credits", 0.0)
            sgpa = sem.get("sgpa", 0.0)
            if cr > 0 and sgpa is not None:
                total_credits += cr
                total_points += cr * sgpa

        if total_credits <= 0:
            return None
        return round(total_points / total_credits, 2)

    @staticmethod
    def calculate_cie_internals(
        isa1: float,
        isa2: float,
        assignment: float,
        project_or_lab: float = 0.0,
        max_marks: float = 50.0,
        isa1_max: float = 40.0,
        isa2_max: Optional[float] = 40.0,
        assignment_max: float = 10.0,
    ) -> Dict[str, Any]:
        """
        CIE (Continuous Internal Evaluation) calculation.
        PESU scheme: ISA 1 and ISA 2 total is 45 marks, Assignment/Lab is 5 marks.
        Total CIE is out of 50 marks.
        """
        if isa1_max == 45.0 or isa2_max in (None, 0.0):
            c_isa = (isa1 / isa1_max * 45.0) if isa1_max > 0 else 0.0
        else:
            c1 = (isa1 / isa1_max * 22.5) if isa1_max > 0 else 0.0
            c2 = (isa2 / isa2_max * 22.5) if (isa2_max and isa2_max > 0) else 0.0
            c_isa = min(45.0, c1 + c2)

        asg_contrib = (assignment / assignment_max * 5.0) if assignment_max > 0 else 0.0
        total_obtained = round(min(max_marks, c_isa + asg_contrib), 2)
        pct = (total_obtained / max_marks * 100.0) if max_marks > 0 else 0.0
        return {
            "total_obtained": total_obtained,
            "max_marks": max_marks,
            "percentage": round(min(100.0, max(0.0, pct)), 2),
            "status": "Safe" if pct >= 40.0 else "Action Required"
        }
