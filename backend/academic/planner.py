"""
Academic planner and task manager for Better PESU Acad.
Manages assignments, deadlines, recurring tasks, timetable, and study goals.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from backend.db import Database


class AcademicPlanner:
    def __init__(self, db: Database):
        self.db = db

    def list_assignments(self, subject_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        asgs = self.db.get_assignments()
        now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        enriched = []
        for a in asgs:
            if subject_filter and a.get("subject") != subject_filter:
                continue

            due = a.get("due_date", "")
            status_tag = "upcoming"
            status_class = ""

            if a.get("status") == "completed":
                status_tag = "Completed"
                status_class = "assignment-done"
            elif due < now_date:
                status_tag = "Overdue"
                status_class = "assignment-late"
            else:
                try:
                    d_due = datetime.strptime(due, "%Y-%m-%d")
                    d_now = datetime.strptime(now_date, "%Y-%m-%d")
                    diff = (d_due - d_now).days
                    if diff == 0:
                        status_tag = "Due today"
                        status_class = "assignment-soon"
                    elif diff <= 3:
                        status_tag = f"Due in {diff}d"
                        status_class = "assignment-soon"
                except ValueError:
                    pass

            item = dict(a)
            item["status_label"] = status_tag
            item["status_class"] = status_class
            enriched.append(item)

        return enriched

    def create_assignment(
        self,
        title: str,
        subject: str,
        due_date: str,
        priority: str = "medium",
        notes: str = ""
    ) -> Dict[str, Any]:
        asg_id = str(uuid.uuid4())
        self.db.save_assignment(
            assignment_id=asg_id,
            title=title.strip(),
            subject=subject.strip(),
            due_date=due_date.strip(),
            priority=priority,
            status="pending",
            notes=notes.strip()
        )
        return {
            "id": asg_id,
            "title": title,
            "subject": subject,
            "due_date": due_date,
            "priority": priority,
            "status": "pending",
            "notes": notes
        }

    def toggle_assignment(self, assignment_id: str, completed: bool) -> None:
        self.db.update_assignment_status(assignment_id, completed)

    def remove_assignment(self, assignment_id: str) -> None:
        self.db.delete_assignment(assignment_id)

    def get_upcoming_schedule(self) -> Dict[str, Any]:
        """Return today's classes and upcoming assignments."""
        today_idx = datetime.now().weekday()  # 0=Monday, 6=Sunday
        today_classes = self.db.get_timetable(day_of_week=today_idx)

        all_assignments = self.list_assignments()
        pending = [a for a in all_assignments if a.get("status") != "completed"][:5]

        return {
            "today_weekday": today_idx,
            "today_classes": today_classes,
            "upcoming_assignments": pending
        }
