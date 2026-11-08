
import os
import json
import subprocess
import argparse
import shutil
import sys
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SLIDES_DIR = str(PROJECT_ROOT / "slides")
METADATA_FILE = str(PROJECT_ROOT / "data" / "courses.json")


def find_libreoffice():
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if executable:
        return executable
    if sys.platform == "darwin":
        for path_str in ("/Applications/LibreOffice.app/Contents/MacOS/soffice",
                         str(Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice")):
            p = Path(path_str)
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
    if sys.platform == "win32":
        for folder in ("C:/Program Files", "C:/Program Files (x86)"):
            path = Path(folder) / "LibreOffice/program/soffice.exe"
            if path.is_file():
                return str(path)
    return None


LIBREOFFICE = find_libreoffice()


def clean(text, limit=80):
    text = re.sub(r'[\\/:*?"<>|]+', "-", " ".join(text.split()))
    return text.strip(" .")[:limit] or "untitled"


def convert_pptx_to_pdf(pptx_path):
    """Convert PPTX to PDF and return the PDF path."""

    pptx_path = os.path.abspath(pptx_path)

    if not os.path.isfile(pptx_path):
        return None

    if not LIBREOFFICE:
        print("LibreOffice not found; skipping conversion of", pptx_path)
        return None

    folder = os.path.dirname(pptx_path)
    pdf_path = os.path.splitext(pptx_path)[0] + ".pdf"

    if os.path.isfile(pdf_path):
        print("Already converted:", pdf_path)
        os.remove(pptx_path)
        return pdf_path

    try:
        result = subprocess.run(
            [
                LIBREOFFICE,
                "--headless",
                "--convert-to", "pdf",
                "--outdir", folder,
                pptx_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0 or not os.path.isfile(pdf_path):
            print("Conversion failed:", pptx_path)
            print(result.stderr or result.stdout)
            return None

        os.remove(pptx_path)
        print("Converted:", pdf_path)

        return pdf_path

    except Exception as e:
        print("Error:", e)
        return None


def update_metadata(metadata, selected_semester=None, selected_subject_id=None):
    """Replace PPTX references with PDF references."""

    updated = 0

    for semester_name, semester in metadata.items():
        if selected_semester is not None and semester_name != selected_semester:
            continue
        for subject in semester.values():
            if selected_subject_id is not None and str(subject.get("id")) != str(selected_subject_id):
                continue
            for classes in subject.get("units", {}).values():
                for class_data in classes:
                    for file in class_data.get("files", []):

                        if file.get("type", "").lower() != "pptx" and not file.get(
                            "name", ""
                        ).lower().endswith(".pptx"):
                            continue

                        old_path = file.get("path", "")

                        # Metadata paths may start with slides/ or be
                        # relative to the slides/ directory.
                        if os.path.isabs(old_path):
                            absolute_path = old_path
                        elif os.path.normpath(old_path).split(os.sep)[0] == "slides":
                            absolute_path = os.path.join(PROJECT_ROOT, old_path)
                        else:
                            absolute_path = os.path.abspath(
                                os.path.join(SLIDES_DIR, old_path)
                            )

                        pdf_path = os.path.splitext(absolute_path)[0] + ".pdf"

                        # Only update metadata when PDF actually exists
                        if not os.path.isfile(pdf_path):
                            print("PDF missing, keeping metadata:", old_path)
                            continue

                        file["name"] = os.path.basename(pdf_path)
                        file["path"] = os.path.relpath(
                            pdf_path,
                            os.path.abspath(SLIDES_DIR)
                        ).replace(os.sep, "/")
                        file["type"] = "pdf"

                        updated += 1

    return updated


def emit_progress(**fields):
    print("BETTERPESU_PROGRESS:" + json.dumps(fields, ensure_ascii=False), flush=True)


def main(selected_semester=None, selected_subject_id=None):
    print("Scanning PPTX files...\n")

    converted = 0
    failed = 0

    selected_prefix = None
    scan_dir = SLIDES_DIR
    if selected_semester is not None and selected_subject_id is None:
        scan_dir = os.path.join(SLIDES_DIR, selected_semester)
    if selected_subject_id is not None:
        with open(METADATA_FILE, encoding="utf-8") as handle:
            existing = json.load(handle)
        subject = next((item for item in existing.get(selected_semester, {}).values()
                        if str(item.get("id")) == str(selected_subject_id)), None)
        if subject is None:
            raise ValueError("Selected subject missing from metadata")
        # The downloader uses a cleaned course code and title as its folder.
        subject_key = next(key for key, item in existing[selected_semester].items()
                           if str(item.get("id")) == str(selected_subject_id))
        selected_prefix = os.path.abspath(os.path.join(SLIDES_DIR, selected_semester, clean(subject_key, 70)))

    if selected_prefix:
        scan_dir = selected_prefix
    # Count pending PPTX files first, so conversion progress is exact.
    pending = []
    for folder, _, files in os.walk(scan_dir):
        for filename in files:
            if filename.lower().endswith(".pptx"):
                pending.append(os.path.join(folder, filename))

    emit_progress(event="conversion_plan", total=len(pending))
    for index, pptx_path in enumerate(pending, 1):
        pdf_path = convert_pptx_to_pdf(pptx_path)
        if pdf_path:
            converted += 1
        else:
            failed += 1
        emit_progress(event="conversion_file", done=index, total=len(pending),
                      converted=converted, conversion_failed=failed)

    if not os.path.isfile(METADATA_FILE):
        print("\ncourses.json not found.")
        return

    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    updated = update_metadata(metadata, selected_semester, selected_subject_id)

    if updated:
        temp_file = METADATA_FILE + ".part"

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        os.replace(temp_file, METADATA_FILE)

    print("\nDone!")
    print("Converted/already available:", converted)
    print("Failed:", failed)
    print("Metadata entries updated:", updated)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--semester")
    parser.add_argument("--subject-id")
    args = parser.parse_args()
    if args.subject_id and not args.semester:
        parser.error("--subject-id requires --semester")
    main(args.semester, args.subject_id)
