"""
Downloader engine for Better PESU Acad course materials.
Connects to PESU Academy, indexes available semesters, subjects, units,
and downloads course slides with duplicate prevention and progress updates.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("betterpesu.downloader")

PESU_HOST = "https://www.pesuacademy.com"
PESU_ACADEMY = f"{PESU_HOST}/Academy"
ADMIN_URL = f"{PESU_ACADEMY}/s/studentProfilePESUAdmin"

WEB_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{PESU_ACADEMY}/s/studentProfilePESU",
}

CALL_REGEX = re.compile(
    r"handleclasscoursecontentunit\(\s*'([^']+)'\s*,\s*'(\d+)'\s*,"
    r"\s*'(\d+)'\s*,\s*'(\d+)'\s*,\s*(\d+)"
)
UNIT_REGEX = re.compile(r"handleclassUnit\('(\d+)'\)")
SLIDE_ID_REGEX = re.compile(r"downloadcoursedoc\('([^']+)'\)")
IFRAME_URL_REGEX = re.compile(r"loadIframe\('([^'#]+)")


def clean_name(text: str, limit: int = 80) -> str:
    text = re.sub(r'[\\/:*?"<>|]+', "-", " ".join(text.split()))
    return text.strip(" .")[:limit] or "untitled"


def get_file_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext.startswith("."):
        ext = ext[1:]
    return ext or "unknown"


def existing_file_check(target_path: Path) -> Optional[Dict[str, str]]:
    """Check if file or converted PDF already exists to avoid redundant downloads."""
    target_path = Path(target_path)
    if target_path.suffix.lower() in (".ppt", ".pptx"):
        pdf = target_path.with_suffix(".pdf")
        if pdf.is_file():
            return {"status": "skipped (PDF already exists)", "filename": pdf.name, "path": str(pdf)}
    if target_path.is_file():
        return {"status": "skipped", "filename": target_path.name, "path": str(target_path)}
    return None


def write_file_safely(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


class DownloaderEngine:
    def __init__(self, session: requests.Session, slides_dir: Path, metadata_file: Path):
        self.session = session
        self.slides_dir = Path(slides_dir)
        self.metadata_file = Path(metadata_file)
        self.slides_dir.mkdir(parents=True, exist_ok=True)

    def get_csrf(self) -> str:
        r = self.session.get(f"{PESU_ACADEMY}/s/studentProfilePESU", headers=WEB_HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        meta = soup.find("meta", {"name": "csrf-token"})
        if meta and meta.get("content"):
            return meta["content"]
        return ""

    def get_semesters(self) -> Dict[str, str]:
        """Fetch available semesters from student profile."""
        now_ms = int(time.time() * 1000)
        # Touch courses shell first
        try:
            self.session.get(
                ADMIN_URL,
                headers=WEB_HEADERS,
                params={
                    "menuId": 653,
                    "url": "studentProfilePESUAdmin",
                    "controllerMode": 6403,
                    "actionType": 5,
                    "id": 0,
                    "selectedData": 0,
                    "_": now_ms,
                },
                timeout=15
            )
        except Exception as e:
            logger.warning("Shell warmup error: %s", e)

        r = self.session.get(
            f"{PESU_ACADEMY}/s/studentProfile/getStudentSemestersPESU",
            headers=WEB_HEADERS,
            params={"_": now_ms},
            timeout=15
        )
        try:
            data = r.json()
            soup = BeautifulSoup(data, "html.parser")
            return {
                opt.get_text(strip=True): opt["value"]
                for opt in soup.find_all("option")
                if opt.get("value")
            }
        except Exception:
            # Fallback parse if returned as raw HTML
            soup = BeautifulSoup(r.text, "html.parser")
            return {
                opt.get_text(strip=True): opt["value"]
                for opt in soup.find_all("option")
                if opt.get("value")
            }

    def get_subjects(self, sem_id: str, csrf: str) -> List[Dict[str, str]]:
        r = self.session.post(
            ADMIN_URL,
            data={
                "controllerMode": 6403,
                "actionType": 38,
                "id": str(sem_id),
                "menuId": 653
            },
            headers={**WEB_HEADERS, "X-CSRF-TOKEN": csrf},
            timeout=20
        )
        subjects = []
        soup = BeautifulSoup(r.text, "html.parser")
        for row in soup.find_all("tr", id=True):
            if row["id"].startswith("rowWiseCourseContent_"):
                tds = row.find_all("td")
                if len(tds) >= 2:
                    subjects.append({
                        "id": row["id"].split("_")[1],
                        "code": tds[0].get_text(strip=True),
                        "title": tds[1].get_text(strip=True)
                    })
        return subjects

    def get_units(self, course_id: str) -> List[Dict[str, str]]:
        now_ms = int(time.time() * 1000)
        r = self.session.get(
            ADMIN_URL,
            headers=WEB_HEADERS,
            params={
                "controllerMode": 6403,
                "actionType": 42,
                "id": course_id,
                "menuId": 653,
                "_": now_ms,
            },
            timeout=20
        )
        units = []
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", onclick=True):
            m = UNIT_REGEX.search(a["onclick"])
            if m:
                units.append({
                    "id": m.group(1),
                    "title": " ".join(a.get_text().split())
                })
        return units

    def get_classes(self, course_id: str, unit_id: str) -> List[Dict[str, Any]]:
        now_ms = int(time.time() * 1000)
        r = self.session.get(
            ADMIN_URL,
            headers=WEB_HEADERS,
            params={
                "controllerMode": 6403,
                "actionType": 43,
                "coursecontentid": unit_id,
                "menuId": 653,
                "selectedData": course_id,
                "subType": 3,
                "_": now_ms,
            },
            timeout=20
        )
        classes: Dict[str, Any] = {}
        soup = BeautifulSoup(r.text, "html.parser")
        for td in soup.find_all("td", onclick=True):
            m = CALL_REGEX.search(td["onclick"])
            if not m:
                continue
            uuid, course, unit, class_no, tab = m.groups()
            c = classes.setdefault(
                uuid,
                {
                    "uuid": uuid,
                    "course_id": course,
                    "unit_id": unit,
                    "class_no": class_no,
                    "title": "",
                    "slides": 0,
                }
            )
            title = td.find("span", class_="short-title")
            if title:
                c["title"] = title.get_text(strip=True)
            if tab == "2" and td.find("a"):
                num = re.search(r"\d+", td.get_text())
                c["slides"] = int(num.group()) if num else 0

        return list(classes.values())

    def get_slides_html(self, c: Dict[str, Any]) -> str:
        now_ms = int(time.time() * 1000)
        r = self.session.get(
            ADMIN_URL,
            headers=WEB_HEADERS,
            params={
                "controllerMode": 6403,
                "actionType": 60,
                "selectedData": c["course_id"],
                "id": 2,
                "unitid": c["uuid"],
                "coursecontentid": c["unit_id"],
                "classno": c["class_no"],
                "menuId": 653,
                "subType": 3,
                "_": now_ms,
            },
            timeout=20
        )
        return r.text

    def _save_from_link(self, link: str, folder: Path, stem: str) -> Dict[str, Any]:
        q = parse_qs(urlparse(link).query)
        disp = unquote(q.get("response-content-disposition", [""])[0])
        m = re.search(r'filename="([^"]+)"', disp)
        ext = os.path.splitext(m.group(1) if m else urlparse(link).path)[1] or ".bin"
        filename = stem + ext
        target_path = folder / filename

        existing = existing_file_check(target_path)
        if existing:
            return existing

        # Retry transient download failures
        for attempt in range(3):
            try:
                f = requests.get(link, timeout=45)
                f.raise_for_status()
                write_file_safely(target_path, f.content)
                return {"status": "saved", "filename": filename, "path": str(target_path)}
            except Exception as e:
                if attempt == 2:
                    logger.error("Download failed after 3 attempts for %s: %s", filename, e)
                    return {"status": f"failed: {e}", "filename": None, "path": None}
                time.sleep(1.0 * (attempt + 1))
        return {"status": "failed", "filename": None, "path": None}

    def _download_link_slide(self, slide_id: str, folder: Path, stem: str) -> Dict[str, Any]:
        r = self.session.get(
            f"{PESU_ACADEMY}/s/referenceMeterials/downloadcoursedoc/{slide_id}",
            headers=WEB_HEADERS,
            allow_redirects=False,
            timeout=20
        )
        link = r.headers.get("location")
        if link:
            return self._save_from_link(link, folder, stem)
        return {"status": f"no link ({r.status_code})", "filename": None, "path": None}

    def _download_eye_slide(self, path: str, folder: Path, stem: str) -> Dict[str, Any]:
        for p in (path, path.replace("/Academy/a/", "/Academy/s/")):
            try:
                r = self.session.get(PESU_HOST + p, headers=WEB_HEADERS, allow_redirects=False, timeout=20)
                if r.headers.get("location"):
                    return self._save_from_link(r.headers["location"], folder, stem)
                ctype = r.headers.get("content-type", "")
                if r.status_code == 200 and "text/html" not in ctype:
                    ext = ".pdf" if "pdf" in ctype else ".bin"
                    filename = stem + ext
                    dest = folder / filename
                    if dest.is_file():
                        return {"status": "skipped", "filename": filename, "path": str(dest)}
                    write_file_safely(dest, r.content)
                    return {"status": "saved", "filename": filename, "path": str(dest)}
            except Exception:
                pass
        return {"status": "failed (eye type)", "filename": None, "path": None}

    def save_metadata(self, metadata: Dict[str, Any]) -> None:
        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(self.metadata_file) + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.metadata_file)

    def run_sync(
        self,
        selected_semester: Optional[str] = None,
        selected_subject_id: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None
    ) -> Dict[str, Any]:
        """
        Execute materials synchronization with live progress callbacks.
        """
        csrf = self.get_csrf()
        available_sems = self.get_semesters()
        if not available_sems:
            raise RuntimeError("Could not find any semesters. Check PESU session.")

        if selected_semester:
            if selected_semester not in available_sems:
                raise ValueError(f"Semester '{selected_semester}' not found in PESU account")
            sems = {selected_semester: available_sems[selected_semester]}
        else:
            sems = available_sems

        metadata: Dict[str, Any] = {}
        if self.metadata_file.is_file():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            except Exception:
                metadata = {}

        # Discover subject plan
        planned: Dict[str, List[Dict[str, str]]] = {}
        for sem_name, sem_id in sems.items():
            subjects = self.get_subjects(sem_id, csrf)
            if selected_subject_id:
                subjects = [s for s in subjects if str(s["id"]) == str(selected_subject_id)]
            planned[sem_name] = subjects

        total_subjects = sum(len(items) for items in planned.values())
        completed_subjects = 0
        files_saved = 0
        files_skipped = 0
        files_failed = 0

        if progress_callback:
            progress_callback({
                "event": "download_plan",
                "total": total_subjects
            })

        for sem_name, sem_id in sems.items():
            if is_cancelled and is_cancelled():
                break

            metadata.setdefault(sem_name, {})

            for sub in planned[sem_name]:
                if is_cancelled and is_cancelled():
                    break

                subj_name = f"{sub['code']} - {sub['title']}"
                subj_dir = clean_name(subj_name, 70)

                metadata[sem_name][subj_name] = {
                    "id": sub["id"],
                    "code": sub["code"],
                    "title": sub["title"],
                    "units": {}
                }

                if progress_callback:
                    progress_callback({
                        "event": "subject_start",
                        "subject": subj_name,
                        "semester": sem_name,
                        "done": completed_subjects,
                        "total": total_subjects,
                        "downloaded": files_saved,
                        "skipped": files_skipped,
                        "failed": files_failed
                    })

                units = self.get_units(sub["id"])
                for unit in units:
                    if is_cancelled and is_cancelled():
                        break

                    unit_dir = clean_name(unit["title"], 60)
                    metadata[sem_name][subj_name]["units"].setdefault(unit["title"], [])
                    folder = self.slides_dir / sem_name / subj_dir / unit_dir

                    classes = self.get_classes(sub["id"], unit["id"])
                    for c in classes:
                        if is_cancelled and is_cancelled():
                            break
                        if not c.get("slides"):
                            continue

                        try:
                            html = self.get_slides_html(c)
                            items = [("link", i) for i in SLIDE_ID_REGEX.findall(html)]
                            items += [("eye", u) for u in IFRAME_URL_REGEX.findall(html)]
                            class_files = []

                            for n, (kind, ref) in enumerate(items, 1):
                                if is_cancelled and is_cancelled():
                                    break

                                stem = f"{int(c['class_no']):02d} - {clean_name(c['title'])}"
                                if len(items) > 1:
                                    stem += f" ({n})"

                                if kind == "link":
                                    result = self._download_link_slide(ref, folder, stem)
                                else:
                                    result = self._download_eye_slide(ref, folder, stem)

                                st = result.get("status", "")
                                if st == "saved":
                                    files_saved += 1
                                elif st.startswith("skipped"):
                                    files_skipped += 1
                                else:
                                    files_failed += 1

                                if progress_callback:
                                    progress_callback({
                                        "event": "file",
                                        "subject": subj_name,
                                        "downloaded": files_saved,
                                        "skipped": files_skipped,
                                        "failed": files_failed
                                    })

                                if result.get("filename"):
                                    full_p = Path(result["path"])
                                    try:
                                        rel_p = full_p.relative_to(self.slides_dir)
                                    except ValueError:
                                        rel_p = full_p
                                    class_files.append({
                                        "name": result["filename"],
                                        "path": str(rel_p).replace("\\", "/"),
                                        "type": get_file_type(result["filename"])
                                    })

                            if class_files:
                                metadata[sem_name][subj_name]["units"][unit["title"]].append({
                                    "class_no": int(c["class_no"]),
                                    "title": c["title"],
                                    "files": class_files
                                })

                        except Exception as e:
                            logger.error("Error reading slides for class %s: %s", c.get("title"), e)

                        time.sleep(0.1)

                self.save_metadata(metadata)
                completed_subjects += 1
                if progress_callback:
                    progress_callback({
                        "event": "subject_complete",
                        "subject": subj_name,
                        "done": completed_subjects,
                        "total": total_subjects,
                        "downloaded": files_saved,
                        "skipped": files_skipped,
                        "failed": files_failed
                    })

        self.save_metadata(metadata)
        return {
            "total_subjects": total_subjects,
            "completed_subjects": completed_subjects,
            "saved": files_saved,
            "skipped": files_skipped,
            "failed": files_failed
        }
