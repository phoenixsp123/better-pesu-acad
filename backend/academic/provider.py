"""
PESU Academy Academic Data Provider.
Safely extracts student attendance and timetable records from authenticated PESU sessions.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
import requests
from bs4 import BeautifulSoup

from backend.db import Database

logger = logging.getLogger("betterpesu.academic.provider")

PESU_BASE = "https://www.pesuacademy.com/Academy"
ADMIN_URL = f"{PESU_BASE}/s/studentProfilePESUAdmin"
MOBILE_DISPATCHER = "https://www.pesuacademy.com/MAcademy/mobile/dispatcher"


class AcademicDataProvider:
    def __init__(self, session: requests.Session, db: Database):
        self.session = session
        self.db = db

    def sync_attendance_for_semester(self, semester_id: str, semester_name: str = "") -> List[Dict[str, Any]]:
        """
        Query PESU Academy attendance endpoint for a given semester ID and update local DB.
        """
        params = {
            "menuId": "660",
            "controllerMode": "6407",
            "actionType": "8",
            "batchClassId": str(semester_id),
            "_": str(int(time.time() * 1000)),
        }
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{PESU_BASE}/s/studentProfilePESU",
        }

        response = self.session.get(ADMIN_URL, params=params, headers=headers, timeout=20)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table", class_="box-shadow") or soup.find(id="studentAttendanceSemester")
        if not table or "Data Not Available" in table.get_text():
            logger.info("No attendance table found or data not available for semester %s", semester_id)
            return []

        results = []
        rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")

        for row in rows:
            tds = row.find_all("td")
            if len(tds) < 3:
                continue

            code = tds[0].get_text(strip=True)
            title = tds[1].get_text(strip=True)
            counts_text = tds[2].get_text(strip=True)

            if "/" not in counts_text:
                continue

            try:
                parts = counts_text.split("/")
                attended = int(re.sub(r"[^\d]", "", parts[0]))
                conducted = int(re.sub(r"[^\d]", "", parts[1]))
            except (ValueError, IndexError):
                continue

            # Upsert into database
            self.db.upsert_attendance(
                subject_code=code,
                subject_name=title,
                attended=attended,
                conducted=conducted,
                source="scraped",
                semester=semester_name
            )

            results.append({
                "subject_code": code,
                "subject_name": title,
                "semester": semester_name,
                "attended": attended,
                "conducted": conducted,
                "percentage": round((attended / conducted * 100.0) if conducted > 0 else 100.0, 2)
            })

        return results

    def sync_timetable(self) -> List[Dict[str, Any]]:
        """
        Query PESU Academy timetable endpoint and persist structured schedule into local DB.
        Uses embedded timeTableTemplateDetailsJson and timeTableJson from PESU Academy AJAX response.
        """
        params = {
            "menuId": "669",
            "controllerMode": "6415",
            "actionType": "5",
            "_": str(int(time.time() * 1000)),
        }
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{PESU_BASE}/s/studentProfilePESU",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            response = self.session.get(ADMIN_URL, params=params, headers=headers, timeout=20)
            if response.status_code != 200:
                logger.warning("Timetable endpoint returned HTTP %s", response.status_code)
                return []

            html = response.text
            entries = []

            # Method 1: Check embedded JavaScript JSON objects
            slots_match = re.search(r'var\s+timeTableTemplateDetailsJson\s*=\s*(.*?);', html, re.DOTALL)
            schedule_match = re.search(r'var\s+timeTableJson\s*=\s*(.*?);', html, re.DOTALL)

            if slots_match and schedule_match:
                try:
                    slots_data = json.loads(slots_match.group(1))
                    sched_data = json.loads(schedule_match.group(1))

                    slot_times = {}
                    for s in slots_data:
                        order = s.get("orderedBy")
                        st = s.get("startTime", "")
                        et = s.get("endTime", "")
                        if order is not None:
                            slot_times[int(order)] = (st, et)

                    self.db.clear_timetable()

                    for key, val_list in sched_data.items():
                        if not key.startswith("ttDivText_") or not val_list:
                            continue
                        parts = key.split("_")
                        if len(parts) < 3:
                            continue
                        try:
                            # 1=Monday, 2=Tuesday, 3=Wednesday, 4=Thursday, 5=Friday, 6=Saturday
                            # Convert to 0-indexed: 0=Monday .. 5=Saturday
                            day_idx = int(parts[1]) - 1
                            slot_idx = int(parts[2])
                        except ValueError:
                            continue

                        if not (0 <= day_idx <= 6):
                            continue

                        raw_text = str(val_list[0])
                        # Remove ttSubject_&& or ttSubject&& prefixes
                        raw_text = re.sub(r'^(?:ttSubject)?[_&]+', '', raw_text).strip()
                        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
                        if not lines:
                            continue

                        full_title = lines[0]
                        full_title = re.sub(r'^(?:ttSubject)?[_&]+', '', full_title).strip()

                        # Split code and name if present
                        code = ""
                        name = full_title
                        match = re.match(r'^([A-Z0-9]{5,12})\s*[-–—:]\s*(.+)$', full_title, re.IGNORECASE)
                        if match:
                            code = match.group(1).strip()
                            name = match.group(2).strip()
                        elif " - " in full_title:
                            code_part, name_part = full_title.split(" - ", 1)
                            if len(code_part) <= 12:
                                code = code_part.strip()
                                name = name_part.strip()

                        # Convert shouting all-caps names into clean readable title case
                        if name.isupper():
                            words = name.split()
                            name = " ".join(
                                w.upper() if w.lower() in ("ai", "i", "ii", "iii", "iv", "ml", "os", "dsa")
                                else (w.lower() if w.lower() in ("and", "for", "in", "of", "to", "the", "its", "with")
                                      else w.capitalize())
                                for w in words
                            )

                        # Extract room if present
                        room = ""
                        for line in lines[1:]:
                            if "room" in line.lower() or "hall" in line.lower() or "lab" in line.lower():
                                room = line
                                break

                        st, et = slot_times.get(slot_idx, ("", ""))
                        # Clean seconds from time string e.g. 08:00:16 AM -> 08:00 AM
                        if st:
                            st = re.sub(r'^(\d{1,2}:\d{2}):\d{2}(\s*[AP]M)?$', r'\1\2', st.strip())
                        if et:
                            et = re.sub(r'^(\d{1,2}:\d{2}):\d{2}(\s*[AP]M)?$', r'\1\2', et.strip())

                        is_lab = "lab" in full_title.lower() or "practical" in full_title.lower() or "lab" in room.lower()

                        self.db.set_timetable_entry(
                            day_of_week=day_idx,
                            period_number=slot_idx,
                            subject_name=name,
                            subject_code=code,
                            start_time=st,
                            end_time=et,
                            room=room,
                            is_lab=is_lab
                        )
                        entries.append({
                            "day_of_week": day_idx,
                            "period_number": slot_idx,
                            "subject_name": name,
                            "subject_code": code,
                            "start_time": st,
                            "end_time": et,
                            "room": room,
                            "is_lab": is_lab
                        })

                    if entries:
                        logger.info("Successfully parsed %d timetable periods from script JSON.", len(entries))
                        return entries
                except Exception as e:
                    logger.warning("Error parsing timetable JSON: %s", e)

            # Method 2: Fallback to HTML table parsing
            soup = BeautifulSoup(html, "html.parser")
            table = soup.find("table", class_="table-bordered") or soup.find("table")
            if table:
                self.db.clear_timetable()
                day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

                for row in table.find_all("tr"):
                    cells = row.find_all(["td", "th"])
                    if not cells:
                        continue
                    header_text = cells[0].get_text(strip=True).lower()[:3]
                    if header_text in day_map:
                        day_idx = day_map[header_text]
                        for period_idx, cell in enumerate(cells[1:], 1):
                            txt = cell.get_text(separator=" ", strip=True)
                            if txt and txt != "-":
                                is_lab = "lab" in txt.lower() or "practical" in txt.lower()
                                self.db.set_timetable_entry(
                                    day_of_week=day_idx,
                                    period_number=period_idx,
                                    subject_name=txt,
                                    is_lab=is_lab
                                )
                                entries.append({
                                    "day_of_week": day_idx,
                                    "period_number": period_idx,
                                    "subject_name": txt,
                                    "is_lab": is_lab
                                })

            return entries
        except Exception as e:
            logger.warning("Could not sync timetable: %s", e)
            return []

    def sync_isa_marks(self, semester_id: Optional[str] = None, semester_name: str = "") -> List[Dict[str, Any]]:
        """
        Query PESU Academy for ISA marks and internal assessment results.
        Tries Web portal Tests/ISA endpoints and mobile dispatcher.
        Persists results into isa_marks DB table and returns structured list.
        """
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{PESU_BASE}/s/studentProfilePESU",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        # 1. Obtain CSRF token from studentProfilePESU
        csrf = ""
        try:
            profile_html = self.session.get(f"{PESU_BASE}/s/studentProfilePESU", headers=headers, timeout=15).text
            soup_profile = BeautifulSoup(profile_html, "html.parser")
            csrf_meta = soup_profile.find("meta", {"name": "csrf-token"})
            if csrf_meta and csrf_meta.get("content"):
                csrf = csrf_meta["content"]
                headers["X-CSRF-TOKEN"] = csrf
        except Exception as e:
            logger.warning("Could not fetch CSRF token for ISA marks: %s", e)

        # 2. Get results semester mapping from /studentProfile/getEsaAndIsaResultSemBySRN
        sem_map: Dict[str, str] = {}
        try:
            r_sem = self.session.get(f"{PESU_BASE}/s/studentProfile/getEsaAndIsaResultSemBySRN", headers=headers, timeout=12)
            if r_sem.status_code == 200:
                for opt in BeautifulSoup(r_sem.text, "html.parser").find_all("option"):
                    val = opt.get("value", "").strip()
                    txt = opt.get_text(strip=True)
                    if val and txt:
                        sem_map[txt] = val
        except Exception as e:
            logger.warning("Could not fetch result semesters: %s", e)

        # Resolve target semester_name and semid
        sem_id_to_use = semester_id
        target_sem_name = semester_name

        if sem_map:
            if target_sem_name and target_sem_name in sem_map:
                sem_id_to_use = sem_map[target_sem_name]
            elif not target_sem_name and sem_id_to_use:
                for name, s_id in sem_map.items():
                    if str(s_id) == str(sem_id_to_use):
                        target_sem_name = name
                        break
            if not sem_id_to_use:
                target_sem_name, sem_id_to_use = list(sem_map.items())[0]
        elif not target_sem_name:
            target_sem_name = "Sem-3"

        parsed_marks: Dict[str, Dict[str, Any]] = {}

        # 3. Hit actionType=8 with semid
        if sem_id_to_use:
            try:
                post_data = {
                    "menuId": "652",
                    "controllerMode": "6402",
                    "actionType": "8",
                    "semid": str(sem_id_to_use),
                }
                if csrf:
                    post_data["_csrf"] = csrf

                resp = self.session.post(ADMIN_URL, data=post_data, headers=headers, timeout=18)
                if resp.status_code == 200 and "dashboard-info-bar" in resp.text:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    sections = soup.find_all("div", class_="clearfix")
                    for sec in sections:
                        head = sec.find("div", class_="header-info")
                        bar = sec.find("div", class_="dashboard-info-bar")
                        if not head or not bar:
                            continue

                        code_tag = head.find("span", class_="lbl-title-light")
                        code = code_tag.get_text(strip=True).replace("-", "").strip() if code_tag else ""
                        full_head = head.get_text(separator=" ", strip=True)
                        name = full_head.replace(code, "").replace("-", "").strip()

                        # Extract course credits if available e.g. "Credits: 4 / 4"
                        cr = 4.0
                        cr_m = re.search(r'Credits?\s*:\s*(\d+(?:\.\d+)?)', full_head, re.IGNORECASE)
                        if cr_m:
                            try:
                                cr = float(cr_m.group(1))
                            except ValueError:
                                cr = 4.0

                        # Clean title
                        name = re.sub(r'Credits?\s*:\s*\d+(?:\s*/\s*\d+)?', '', name, flags=re.IGNORECASE).strip()
                        if name.isupper():
                            words = name.split()
                            name = " ".join(
                                w.upper() if w.lower() in ("ai", "i", "ii", "iii", "iv", "ml", "os", "dsa", "c", "ip")
                                else (w.lower() if w.lower() in ("and", "for", "in", "of", "to", "the", "its", "with")
                                      else w.capitalize())
                                for w in words
                            )

                        code_u = (code or "").upper()
                        name_u = (name or "").upper()
                        is_cie = code_u.startswith("UZ") or bool(re.search(r"\bCIE\b", code_u) or re.search(r"\bCIE\b", name_u) or "INNOVATION" in name_u)
                        default_isa_max = 45.0 if is_cie else 40.0

                        isa1_val, isa1_max = None, default_isa_max
                        isa2_val, isa2_max = None, default_isa_max
                        asg_val, asg_max = None, 10.0
                        lab_val, lab_max = None, 10.0
                        final_cie = None
                        has_isa2_div = False

                        for d in bar.find_all("div", recursive=False):
                            lbl_el = d.find("h6")
                            if not lbl_el:
                                continue
                            lbl = lbl_el.get_text(strip=True).upper()
                            d_txt = d.get_text(strip=True).replace(lbl_el.get_text(strip=True), "")
                            m = re.search(r'([\d.]+)(?:\s*/\s*([\d.]+))?', d_txt)
                            score = float(m.group(1)) if m else None
                            max_s = float(m.group(2)) if (m and m.group(2)) else None

                            if "ISA 1" in lbl or "ISA-1" in lbl:
                                isa1_val = score
                                if max_s:
                                    isa1_max = max_s
                            elif "ISA 2" in lbl or "ISA-2" in lbl:
                                has_isa2_div = True
                                isa2_val = score
                                if max_s:
                                    isa2_max = max_s
                            elif any(k in lbl for k in ("ASSIGNMENT", "QUIZ", "AWA")):
                                asg_val = score
                                if max_s:
                                    asg_max = max_s
                            elif any(k in lbl for k in ("MATLAB", "LAB", "PROJECT")):
                                lab_val = score
                                if max_s:
                                    lab_max = max_s
                            elif any(k in lbl for k in ("FINAL ISA", "CIE")):
                                if score is not None and score > 0:
                                    final_cie = score

                        if not has_isa2_div:
                            isa2_max = isa1_max

                        if code:
                            parsed_marks[code] = {
                                "subject_code": code,
                                "subject_name": name,
                                "semester": target_sem_name,
                                "credits": cr,
                                "isa1_score": isa1_val,
                                "isa1_max": isa1_max,
                                "isa2_score": isa2_val,
                                "isa2_max": isa2_max,
                                "assignment_score": asg_val if asg_val is not None else lab_val,
                                "assignment_max": asg_max,
                                "project_or_lab": lab_val,
                                "project_max": lab_max or 10.0,
                                "cie_total": final_cie,
                                "source": "pesu_academy"
                            }
            except Exception as e:
                logger.warning("Error fetching ISA marks from PESU action 8: %s", e)

        # Fallback: If no marks returned, seed from attendance subjects for this semester
        if not parsed_marks:
            existing_attendance = self.db.get_all_attendance(semester=target_sem_name)
            for a in existing_attendance:
                code = a["subject_code"]
                code_u = code.upper()
                name_u = (a.get("subject_name") or "").upper()
                is_cie = code_u.startswith("UZ") or bool(re.search(r"\bCIE\b", code_u) or re.search(r"\bCIE\b", name_u) or "INNOVATION" in name_u)
                default_isa_max = 45.0 if is_cie else 40.0
                parsed_marks[code] = {
                    "subject_code": code,
                    "subject_name": a["subject_name"],
                    "semester": target_sem_name,
                    "credits": 4.0,
                    "isa1_score": None,
                    "isa1_max": default_isa_max,
                    "isa2_score": None,
                    "isa2_max": default_isa_max,
                    "esa_max": 50.0 if is_cie else 100.0,
                    "is_cie": is_cie,
                    "assignment_score": None,
                    "assignment_max": 10.0,
                    "project_or_lab": None,
                    "project_max": 10.0,
                    "cie_total": None,
                    "source": "attendance_seed"
                }

        # Clear old marks for this semester before upserting fresh
        if target_sem_name:
            self.db.clear_isa_marks(semester=target_sem_name)

        # Persist into DB
        results = []
        for code, item in parsed_marks.items():
            self.db.upsert_isa_marks(
                subject_code=code,
                subject_name=item["subject_name"],
                semester=item["semester"],
                credits=item["credits"],
                isa1_score=item["isa1_score"],
                isa1_max=item["isa1_max"],
                isa2_score=item["isa2_score"],
                isa2_max=item["isa2_max"],
                assignment_score=item["assignment_score"],
                assignment_max=item["assignment_max"],
                project_or_lab=item["project_or_lab"],
                project_max=item["project_max"],
                cie_total=item.get("cie_total"),
                source=item.get("source", "scraped")
            )
            results.append(item)

        logger.info("Synced ISA marks for %d courses (%s)", len(results), target_sem_name)
        return results
