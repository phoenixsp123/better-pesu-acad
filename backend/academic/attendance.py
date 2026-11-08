"""
Attendance calculation, projection, and simulation engine for Better PESU Acad.
Handles verified mathematical formulas for attendance tracking, target calculation,
bunking thresholds, multi-step scenario simulation, and CSV import/export.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class AttendanceAnalysis:
    subject_code: str
    subject_name: str
    attended: int
    conducted: int
    missed: int
    current_percentage: float
    target_percentage: float
    classes_needed: Optional[int]
    classes_can_bunk: int
    status: str  # "safe", "warning", "critical"
    is_impossible_target: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AttendanceCalculator:
    """
    Mathematical attendance engine implementing PESU attendance dynamics.
    """

    @staticmethod
    def calculate_current_percentage(attended: int, conducted: int) -> float:
        """
        Calculate current attendance percentage A / T * 100.
        Returns 100.0 if conducted == 0 (no classes held yet).
        """
        if conducted <= 0:
            return 100.0
        pct = (attended / conducted) * 100.0
        return round(min(100.0, max(0.0, pct)), 2)

    @staticmethod
    def calculate_after_bunking(attended: int, conducted: int, bunk_count: int) -> float:
        """
        Project attendance after bunking k future classes: A / (T + k) * 100.
        """
        if bunk_count < 0:
            raise ValueError("Bunk count cannot be negative")
        new_total = conducted + bunk_count
        if new_total <= 0:
            return 100.0
        return round((attended / new_total) * 100.0, 2)

    @staticmethod
    def calculate_after_attending(attended: int, conducted: int, attend_count: int) -> float:
        """
        Project attendance after attending n consecutive classes: (A + n) / (T + n) * 100.
        """
        if attend_count < 0:
            raise ValueError("Attend count cannot be negative")
        new_total = conducted + attend_count
        if new_total <= 0:
            return 100.0
        return round(((attended + attend_count) / new_total) * 100.0, 2)

    @staticmethod
    def classes_needed_to_reach_target(
        attended: int,
        conducted: int,
        target_percentage: float = 75.0
    ) -> Tuple[Optional[int], bool]:
        """
        Find minimum integer n >= 0 required to reach or restore target p:
            (A + n) / (T + n) >= p  =>  n >= (p*T - A) / (1 - p)
        Returns (n, is_impossible).
        If already at or above target, returns (0, False).
        If target is 100% and a class has been missed (A < T), 100% is mathematically
        impossible to reach, returning (None, True).
        """
        if conducted <= 0:
            return (0, False)

        target_fraction = target_percentage / 100.0
        current_fraction = attended / conducted

        if current_fraction >= target_fraction or target_fraction <= 0.0:
            return (0, False)

        # Edge case: target is 100% (or above 99.999%)
        if target_fraction >= 1.0:
            if attended == conducted:
                return (0, False)
            return (None, True)

        numerator = (target_fraction * conducted) - attended
        denominator = 1.0 - target_fraction

        if denominator <= 0:
            return (None, True)

        req = math.ceil(numerator / denominator)
        return (max(0, req), False)

    @staticmethod
    def classes_can_bunk_retaining_target(
        attended: int,
        conducted: int,
        target_percentage: float = 75.0
    ) -> int:
        """
        Find maximum nonnegative integer k that can be missed while retaining target p:
            A / (T + k) >= p  =>  k <= (A / p) - T
        """
        if conducted <= 0:
            return 0

        target_fraction = target_percentage / 100.0
        if target_fraction <= 0.0:
            return 9999  # Unlimited bunking if target is 0%

        if target_fraction > 1.0:
            return 0

        current_fraction = attended / conducted
        if current_fraction < target_fraction:
            return 0  # Already below target

        max_k = math.floor((attended / target_fraction) - conducted)
        return max(0, max_k)

    @classmethod
    def analyze_subject(
        cls,
        subject_code: str,
        subject_name: str,
        attended: int,
        conducted: int,
        target_percentage: float = 75.0
    ) -> AttendanceAnalysis:
        """
        Produce a full analysis for a subject with attendance status, needed classes,
        and bunk tolerance.
        """
        missed = max(0, conducted - attended)
        pct = cls.calculate_current_percentage(attended, conducted)
        needed, impossible = cls.classes_needed_to_reach_target(attended, conducted, target_percentage)
        can_bunk = cls.classes_can_bunk_retaining_target(attended, conducted, target_percentage)

        # Status categorization
        if pct >= target_percentage + 10.0:
            status = "safe"
        elif pct >= target_percentage:
            status = "warning"
        else:
            status = "critical"

        return AttendanceAnalysis(
            subject_code=subject_code,
            subject_name=subject_name,
            attended=attended,
            conducted=conducted,
            missed=missed,
            current_percentage=pct,
            target_percentage=target_percentage,
            classes_needed=needed,
            classes_can_bunk=can_bunk,
            status=status,
            is_impossible_target=impossible
        )

    @classmethod
    def generate_bunk_matrix(
        cls,
        attended: int,
        conducted: int,
        max_miss: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Generate answers for "What happens if I miss 1, 2, 3... classes?"
        """
        results = []
        for k in range(1, max_miss + 1):
            projected = cls.calculate_after_bunking(attended, conducted, k)
            results.append({
                "miss_count": k,
                "projected_percentage": projected,
                "percentage_drop": round(cls.calculate_current_percentage(attended, conducted) - projected, 2)
            })
        return results

    @classmethod
    def simulate_custom_chain(
        cls,
        initial_attended: int,
        initial_conducted: int,
        actions: List[str]  # e.g. ["attend", "attend", "bunk", "attend"]
    ) -> List[Dict[str, Any]]:
        """
        Step-by-step projection simulating custom sequences of future classes.
        """
        history = [{
            "step": 0,
            "action": "current",
            "attended": initial_attended,
            "conducted": initial_conducted,
            "percentage": cls.calculate_current_percentage(initial_attended, initial_conducted)
        }]

        curr_att = initial_attended
        curr_cond = initial_conducted

        for idx, act in enumerate(actions, 1):
            if act.lower() in ("attend", "present", "1"):
                curr_att += 1
                curr_cond += 1
                action_name = "Attended"
            elif act.lower() in ("bunk", "absent", "miss", "0"):
                curr_cond += 1
                action_name = "Bunked"
            else:
                continue

            history.append({
                "step": idx,
                "action": action_name,
                "attended": curr_att,
                "conducted": curr_cond,
                "percentage": cls.calculate_current_percentage(curr_att, curr_cond)
            })

        return history


def export_attendance_to_csv(analyses: List[AttendanceAnalysis]) -> str:
    """Generate RFC 4180 compliant CSV string of attendance records."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Subject Code",
        "Subject Name",
        "Classes Attended",
        "Classes Conducted",
        "Classes Missed",
        "Current Percentage",
        "Target Percentage",
        "Classes Needed",
        "Can Bunk",
        "Status"
    ])
    for a in analyses:
        needed_str = "Impossible" if a.is_impossible_target else str(a.classes_needed if a.classes_needed is not None else 0)
        writer.writerow([
            a.subject_code,
            a.subject_name,
            a.attended,
            a.conducted,
            a.missed,
            f"{a.current_percentage}%",
            f"{a.target_percentage}%",
            needed_str,
            a.classes_can_bunk,
            a.status.capitalize()
        ])
    return output.getvalue()


def parse_attendance_csv(csv_content: str) -> List[Dict[str, Any]]:
    """
    Parse uploaded CSV data, handling flexible column naming.
    """
    records = []
    reader = csv.reader(io.StringIO(csv_content.strip()))
    header = next(reader, None)
    if not header:
        return []

    # Map headers
    clean_cols = [c.strip().lower().replace(" ", "_") for c in header]
    code_idx = -1
    name_idx = -1
    att_idx = -1
    cond_idx = -1
    target_idx = -1

    for idx, col in enumerate(clean_cols):
        if "code" in col:
            code_idx = idx
        elif "name" in col or "subject" in col or "title" in col:
            if name_idx == -1:
                name_idx = idx
        elif "attended" in col or "present" in col:
            att_idx = idx
        elif "conducted" in col or "total" in col:
            cond_idx = idx
        elif "target" in col:
            target_idx = idx

    # If simple 4-column fallback
    if code_idx == -1 and len(header) >= 4:
        code_idx, name_idx, att_idx, cond_idx = 0, 1, 2, 3

    for row in reader:
        if not row or len(row) < 3:
            continue
        try:
            code = row[code_idx].strip() if code_idx != -1 and code_idx < len(row) else f"SUBJ-{len(records)+1}"
            name = row[name_idx].strip() if name_idx != -1 and name_idx < len(row) else code
            att = int(float(row[att_idx].strip())) if att_idx != -1 and att_idx < len(row) else 0
            cond = int(float(row[cond_idx].strip())) if cond_idx != -1 and cond_idx < len(row) else 0
            target = float(row[target_idx].replace("%", "").strip()) if target_idx != -1 and target_idx < len(row) and row[target_idx].strip() else 75.0

            if cond < att:
                cond = att  # Normalize invalid total

            records.append({
                "subject_code": code or f"SUBJ-{len(records)+1}",
                "subject_name": name or code,
                "attended": att,
                "conducted": cond,
                "target_percentage": target
            })
        except (ValueError, IndexError):
            continue

    return records
