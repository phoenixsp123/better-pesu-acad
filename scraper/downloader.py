import os
import argparse
import json
import pickle
import re
import time
import io
import sys
from contextlib import redirect_stdout
from urllib.parse import urlparse, parse_qs, unquote
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SLIDES_DIR = PROJECT_ROOT / "slides"
METADATA_FILE = PROJECT_ROOT / "data" / "courses.json"
SESSION_FILE = PROJECT_ROOT / "session.pkl"
load_dotenv(PROJECT_ROOT / ".env")

HOST = "https://www.pesuacademy.com"
BASE = f"{HOST}/Academy"
ADMIN = f"{BASE}/s/studentProfilePESUAdmin"

HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE}/s/studentProfilePESU",
}

CALL = re.compile(
    r"handleclasscoursecontentunit\(\s*'([^']+)'\s*,\s*'(\d+)'\s*,"
    r"\s*'(\d+)'\s*,\s*'(\d+)'\s*,\s*(\d+)"
)

UNIT = re.compile(r"handleclassUnit\('(\d+)'\)")
SLIDE_ID = re.compile(r"downloadcoursedoc\('([^']+)'\)")
IFRAME_URL = re.compile(r"loadIframe\('([^'#]+)")


# ============================================================
# SESSION
# ============================================================

s = requests.Session()

s.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Referer": BASE + "/"
})


# ============================================================
# CONFIGURATION
# ============================================================




# ============================================================
# HELPERS
# ============================================================

def soup(html):
    return BeautifulSoup(html, "html.parser")


def now_ms():
    return int(time.time() * 1000)


def clean(text, limit=80):
    text = re.sub(
        r'[\\/:*?"<>|]+',
        "-",
        " ".join(text.split())
    )

    return text.strip(" .")[:limit] or "untitled"


def get_file_type(filename):
    """
    Returns the file extension/type.
    Example:
        notes.pdf -> pdf
        lecture.pptx -> pptx
    """

    extension = os.path.splitext(filename)[1].lower()

    if extension.startswith("."):
        extension = extension[1:]

    return extension or "unknown"


def save_metadata(metadata):
    """
    Saves metadata safely.

    The file is first written as .part and then renamed,
    so the frontend never sees a half-written JSON file.
    """

    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    tmp = str(METADATA_FILE) + ".part"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(
            metadata,
            f,
            indent=2,
            ensure_ascii=False
        )

    os.replace(tmp, METADATA_FILE)


# Structured progress messages consumed by app.py.
# Ordinary terminal output is unchanged for manual runs.
def emit_progress(**fields):
    print("BETTERPESU_PROGRESS:" + json.dumps(fields, ensure_ascii=False), flush=True)


# ============================================================
# LOGIN AND LISTING
# ============================================================

def login(save_session=True):

    csrf = soup(
        s.get(BASE + "/").text
    ).find(
        "input",
        {"name": "_csrf"}
    )["value"]

    r = s.post(
        f"{BASE}/j_spring_security_check",
        data={
            "j_username": os.environ["PESU_USER"],
            "j_password": os.environ["PESU_PASS"],
            "_csrf": csrf,
        }
    )

    if "j_username" in r.text:
        raise SystemExit(
            "Login failed: check .env credentials"
        )

    if save_session:
        with open(SESSION_FILE, "wb") as f:
            pickle.dump(s.cookies, f)


def get_csrf():

    page = s.get(
        f"{BASE}/s/studentProfilePESU",
        headers=HEADERS
    ).text

    return soup(page).find(
        "meta",
        {"name": "csrf-token"}
    )["content"]

def get_semesters():

    # Load the My Courses shell first, like the browser does
    r_shell = s.get(
        ADMIN,
        headers=HEADERS,
        params={
            "menuId": 653,
            "url": "studentProfilePESUAdmin",
            "controllerMode": 6403,
            "actionType": 5,
            "id": 0,
            "selectedData": 0,
            "_": now_ms(),
        }
    )

    print("Shell status:", r_shell.status_code)
    print("Shell URL:", r_shell.url)

    r = s.get(
        f"{BASE}/s/studentProfile/getStudentSemestersPESU",
        headers=HEADERS,
        params={
            "_": now_ms()
        }
    )

    print("Semester status:", r.status_code)
    print("Semester URL:", r.url)
    print("Content-Type:", r.headers.get("content-type"))
    print("Response preview:")
    print(r.text[:1000])

    try:
        data = r.json()
    except Exception:
        raise RuntimeError(
            "\nPESU did not return JSON for the semester request.\n"
            f"Status: {r.status_code}\n"
            f"Content-Type: {r.headers.get('content-type')}\n"
            f"Response: {r.text[:500]}"
        )

    return {
        o.text.strip(): o["value"]
        for o in soup(data).find_all("option")
    }


def get_subjects(sem_id, csrf):

    r = s.post(
        ADMIN,
        data={
            "controllerMode": 6403,
            "actionType": 38,
            "id": sem_id,
            "menuId": 653
        },
        headers={
            **HEADERS,
            "X-CSRF-TOKEN": csrf
        }
    )

    subjects = []

    for row in soup(r.text).find_all("tr", id=True):

        if row["id"].startswith(
            "rowWiseCourseContent_"
        ):

            tds = row.find_all("td")

            subjects.append({
                "id": row["id"].split("_")[1],
                "code": tds[0].get_text(strip=True),
                "title": tds[1].get_text(strip=True)
            })

    return subjects


def get_course_page(course_id):

    r = s.get(
        ADMIN,
        headers=HEADERS,
        params={
            "controllerMode": 6403,
            "actionType": 42,
            "id": course_id,
            "menuId": 653,
            "_": now_ms(),
        }
    )

    return soup(r.text)


def get_units(course_id):

    units = []

    for a in get_course_page(course_id).find_all(
        "a",
        onclick=True
    ):

        m = UNIT.search(a["onclick"])

        if m:

            units.append({
                "id": m.group(1),
                "title": " ".join(
                    a.get_text().split()
                )
            })

    return units


def get_classes(course_id, unit_id):

    r = s.get(
        ADMIN,
        headers=HEADERS,
        params={
            "controllerMode": 6403,
            "actionType": 43,
            "coursecontentid": unit_id,
            "menuId": 653,
            "selectedData": course_id,
            "subType": 3,
            "_": now_ms(),
        }
    )

    classes = {}

    for td in soup(r.text).find_all(
        "td",
        onclick=True
    ):

        m = CALL.search(td["onclick"])

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

        title = td.find(
            "span",
            class_="short-title"
        )

        if title:
            c["title"] = title.get_text(
                strip=True
            )

        if tab == "2" and td.find("a"):

            num = re.search(
                r"\d+",
                td.get_text()
            )

            c["slides"] = (
                int(num.group())
                if num
                else 0
            )

    return list(classes.values())


def get_slides(c):

    r = s.get(
        ADMIN,
        headers=HEADERS,
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
            "_": now_ms(),
        }
    )

    return r.text


# ============================================================
# FILE WRITING
# ============================================================

def write_file(path, data):

    os.makedirs(
        os.path.dirname(path),
        exist_ok=True
    )

    tmp = path + ".part"

    with open(tmp, "wb") as out:
        out.write(data)

    os.replace(
        tmp,
        path
    )


# ============================================================
# DOWNLOADING
# ============================================================

def existing_file_result(path):
    """Skip a PowerPoint download if its converted PDF already exists."""
    original = Path(path)
    if original.suffix.lower() in (".ppt", ".pptx"):
        pdf = original.with_suffix(".pdf")
        if pdf.is_file():
            return {"status": "skipped (PDF already exists)",
                    "filename": pdf.name, "path": str(pdf)}
    if original.is_file():
        return {"status": "skipped", "filename": original.name,
                "path": str(original)}
    return None


def save_from_link(link, folder, stem):

    q = parse_qs(
        urlparse(link).query
    )

    disp = unquote(
        q.get(
            "response-content-disposition",
            [""]
        )[0]
    )

    m = re.search(
        r'filename="([^"]+)"',
        disp
    )

    ext = os.path.splitext(
        m.group(1)
        if m
        else urlparse(link).path
    )[1] or ".bin"

    filename = stem + ext

    path = os.path.join(
        folder,
        filename
    )

    existing = existing_file_result(path)
    if existing:
        return existing

    f = requests.get(
        link,
        timeout=60
    )

    f.raise_for_status()

    write_file(
        path,
        f.content
    )

    return {
        "status": "saved",
        "filename": filename,
        "path": path
    }


def download_link_slide(
    slide_id,
    folder,
    stem
):

    r = s.get(
        f"{BASE}/s/referenceMeterials/downloadcoursedoc/{slide_id}",
        headers=HEADERS,
        allow_redirects=False
    )

    link = r.headers.get("location")

    if link:
        return save_from_link(
            link,
            folder,
            stem
        )

    return {
        "status": f"no link ({r.status_code})",
        "filename": None,
        "path": None
    }


def download_eye_slide(
    path,
    folder,
    stem
):

    # Tries both URL variants.

    for p in (
        path,
        path.replace(
            "/Academy/a/",
            "/Academy/s/"
        )
    ):

        r = s.get(
            HOST + p,
            headers=HEADERS,
            allow_redirects=False
        )

        # Signed redirect
        if r.headers.get("location"):

            return save_from_link(
                r.headers["location"],
                folder,
                stem
            )

        # Direct file
        ctype = r.headers.get(
            "content-type",
            ""
        )

        if (
            r.status_code == 200
            and
            "text/html" not in ctype
        ):

            extension = (
                ".pdf"
                if "pdf" in ctype
                else ".bin"
            )

            filename = stem + extension

            dest = os.path.join(
                folder,
                filename
            )

            if os.path.exists(dest):

                return {
                    "status": "skipped",
                    "filename": filename,
                    "path": dest
                }

            write_file(
                dest,
                r.content
            )

            return {
                "status": "saved",
                "filename": filename,
                "path": dest
            }

    return {
        "status": "failed (eye type)",
        "filename": None,
        "path": None
    }


# ============================================================
# SEMESTER SELECTION
# ============================================================

def choose_semesters(sems):

    names = list(sems)

    print("\nSemesters:")

    for i, name in enumerate(
        names,
        1
    ):
        print(
            f"  {i}. {name}"
        )

    print("  a. All")

    pick = input(
        "Choose (e.g. 3 or 1,3 or a): "
    ).strip().lower()

    if pick in (
        "a",
        "all",
        ""
    ):
        return sems

    chosen = {}

    for part in pick.split(","):

        part = part.strip()

        if (
            part.isdigit()
            and
            1 <= int(part) <= len(names)
        ):

            chosen[
                names[int(part) - 1]
            ] = sems[
                names[int(part) - 1]
            ]

        else:

            print(
                "Ignoring invalid choice:",
                part
            )

    return chosen


# ============================================================
# MAIN DOWNLOAD FUNCTION
# ============================================================

def download_all(root=None, selected_semester=None, selected_subject_id=None, all_semesters=False):
    if root is None:
        root = str(SLIDES_DIR)
    root = os.path.abspath(os.fspath(root))

    csrf = get_csrf()

    available_sems = get_semesters()
    if selected_semester is not None:
        if selected_semester not in available_sems:
            raise ValueError("Selected semester not found on PESU Academy")
        sems = {selected_semester: available_sems[selected_semester]}
    elif all_semesters:
        sems = available_sems
    else:
        sems = choose_semesters(available_sems)

    if not sems:
        raise SystemExit(
            "Nothing selected."
        )

    # --------------------------------------------------------
    # Metadata structure
    # --------------------------------------------------------

    metadata = {}
    if os.path.isfile(METADATA_FILE):
        with open(METADATA_FILE, encoding="utf-8") as handle:
            metadata = json.load(handle)
    matched_subject = False

    # Discover subject counts before downloading for a meaningful progress bar.
    planned = {}
    for sem_name, sem_id in sems.items():
        subjects = get_subjects(sem_id, csrf)
        if selected_subject_id is not None:
            subjects = [sub for sub in subjects if str(sub["id"]) == str(selected_subject_id)]
        planned[sem_name] = subjects
    total_subjects = sum(len(items) for items in planned.values())
    completed_subjects = 0
    files_saved = 0
    files_skipped = 0
    files_failed = 0
    emit_progress(event="download_plan", total=total_subjects)

    for sem_name, sem_id in sems.items():

        print(
            f"\n{'=' * 60}"
        )

        print(
            f"SEMESTER: {sem_name}"
        )

        print(
            f"{'=' * 60}"
        )

        metadata.setdefault(
            sem_name,
            {}
        )

        # ----------------------------------------------------
        # SUBJECTS
        # ----------------------------------------------------

        for sub in planned[sem_name]:
            if selected_subject_id is not None and str(sub["id"]) != str(selected_subject_id):
                continue
            matched_subject = True

            subj_name = (
                f"{sub['code']} - "
                f"{sub['title']}"
            )

            subj_dir = clean(
                subj_name,
                70
            )

            metadata[
                sem_name
            ][subj_name] = {
                "id": sub["id"],
                "code": sub["code"],
                "title": sub["title"],
                "units": {}
            }

            print(
                f"\nSubject: {subj_name}"
            )
            emit_progress(event="subject_start", subject=subj_name,
                          semester=sem_name, done=completed_subjects, total=total_subjects,
                          downloaded=files_saved, skipped=files_skipped, failed=files_failed)

            # ------------------------------------------------
            # UNITS
            # ------------------------------------------------

            for unit in get_units(
                sub["id"]
            ):

                unit_dir = clean(
                    unit["title"],
                    60
                )

                metadata[
                    sem_name
                ][subj_name][
                    "units"
                ].setdefault(
                    unit["title"],
                    []
                )

                folder = os.path.join(
                    root,
                    sem_name,
                    subj_dir,
                    unit_dir
                )

                # --------------------------------------------
                # CLASSES
                # --------------------------------------------

                for c in get_classes(
                    sub["id"],
                    unit["id"]
                ):

                    if not c["slides"]:
                        continue

                    try:

                        html = get_slides(c)

                        items = [
                            ("link", i)
                            for i in SLIDE_ID.findall(
                                html
                            )
                        ]

                        items += [
                            ("eye", u)
                            for u in IFRAME_URL.findall(
                                html
                            )
                        ]

                        files = []

                        # ------------------------------------
                        # FILES / SLIDES
                        # ------------------------------------

                        for n, (
                            kind,
                            ref
                        ) in enumerate(
                            items,
                            1
                        ):

                            stem = (
                                f"{int(c['class_no']):02d} - "
                                f"{clean(c['title'])}"
                            )

                            if len(items) > 1:

                                stem += (
                                    f" ({n})"
                                )

                            if kind == "link":

                                result = (
                                    download_link_slide(
                                        ref,
                                        folder,
                                        stem
                                    )
                                )

                            else:

                                result = (
                                    download_eye_slide(
                                        ref,
                                        folder,
                                        stem
                                    )
                                )

                            status = result["status"]
                            if status == "saved":
                                files_saved += 1
                            elif status.startswith("skipped"):
                                files_skipped += 1
                            else:
                                files_failed += 1
                            emit_progress(event="file", subject=subj_name,
                                          downloaded=files_saved, skipped=files_skipped,
                                          failed=files_failed)
                            print(
                                result["status"],
                                "|",
                                unit_dir,
                                "|",
                                stem
                            )

                            # --------------------------------
                            # ADD TO METADATA
                            # --------------------------------

                            if result["filename"]:

                                relative_path = os.path.relpath(
                                    result["path"],
                                    root
                                )

                                relative_path = (
                                    relative_path
                                    .replace(
                                        os.sep,
                                        "/"
                                    )
                                )

                                files.append({
                                    "name": result[
                                        "filename"
                                    ],
                                    "path": relative_path,
                                    "type": get_file_type(
                                        result[
                                            "filename"
                                        ]
                                    )
                                })

                        # ------------------------------------
                        # SAVE CLASS METADATA
                        # ------------------------------------

                        if files:

                            metadata[
                                sem_name
                            ][subj_name][
                                "units"
                            ][unit["title"]].append({

                                "class_no": int(
                                    c["class_no"]
                                ),

                                "title": c["title"],

                                "files": files
                            })

                        else:

                            print(
                                "no slide items found |",
                                unit_dir,
                                "|",
                                c["title"]
                            )

                    except Exception as e:

                        print(
                            "ERROR |",
                            unit_dir,
                            "|",
                            c["title"],
                            "|",
                            repr(e)
                        )

                    time.sleep(0.5)

            # ------------------------------------------------
            # SAVE AFTER EACH SUBJECT
            # ------------------------------------------------

            save_metadata(
                metadata
            )
            completed_subjects += 1
            emit_progress(event="subject_complete", subject=subj_name,
                          done=completed_subjects, total=total_subjects,
                          downloaded=files_saved, skipped=files_skipped, failed=files_failed)

    if selected_subject_id is not None and not matched_subject:
        raise ValueError("Selected subject not found in that semester")

    # --------------------------------------------------------
    # FINAL SAVE
    # --------------------------------------------------------

    save_metadata(
        metadata
    )

    print(
        f"\nMetadata saved to: "
        f"{METADATA_FILE}"
    )


# ============================================================
# PROGRAM ENTRY POINT
# ============================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--semester")
    parser.add_argument("--subject-id")
    parser.add_argument("--all-semesters", action="store_true")
    parser.add_argument("--list-semesters", action="store_true")
    args = parser.parse_args()
    if args.subject_id and not args.semester:
        parser.error("--subject-id requires --semester")
    if args.all_semesters and args.semester:
        parser.error("--all-semesters cannot be combined with --semester")
    if args.list_semesters and (args.all_semesters or args.semester or args.subject_id):
        parser.error("--list-semesters cannot be combined with sync options")
    if args.list_semesters:
        # Suppress diagnostic print statements so stdout is valid JSON.
        with redirect_stdout(io.StringIO()):
            login(save_session=False)
            semester_names = list(get_semesters().keys())
        print(json.dumps(semester_names, ensure_ascii=False))
        sys.exit(0)
    login()
    download_all(selected_semester=args.semester,
                 selected_subject_id=args.subject_id,
                 all_semesters=args.all_semesters)