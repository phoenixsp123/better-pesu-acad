"""
Unit PDF Merger for Better PESU Acad.
Combines all lecture slide PDFs in a unit folder into a single, comprehensive
unit study PDF (e.g. 00 - [Combined] Unit 1 - Title.pdf), naturally sorted by lecture number.
Also handles incremental re-merging during sync operations.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from pypdf import PdfWriter
except ImportError:
    PdfWriter = None

logger = logging.getLogger("betterpesu.pdf_merger")

COMBINED_PREFIX = "00 - [Combined]"


def natural_sort_key(file_path: Path) -> tuple:
    """Sort filenames numerically by class/lecture number, then by name."""
    name = file_path.name
    # Extract the first integer in the filename for numerical ordering
    num_match = re.search(r"(\d+)", name)
    if num_match:
        return (0, int(num_match.group(1)), name.lower())
    return (1, 999999, name.lower())


def is_combined_pdf(filename: str) -> bool:
    """Check if file is an automatically generated combined PDF to avoid merging into itself."""
    fn = filename.lower()
    return "[combined]" in fn or fn.startswith("00 - [combined]") or "all lectures combined" in fn


def clean_name(text: str, limit: int = 80) -> str:
    text = re.sub(r'[\\/:*?"<>|]+', "-", " ".join(text.split()))
    return text.strip(" .")[:limit] or "untitled"


def merge_unit_folder(unit_dir: Path) -> Optional[Path]:
    """
    Finds all individual slide PDFs in unit_dir, sorts them numerically,
    and merges them into a single unit PDF.
    Returns the path to the merged PDF, or None if fewer than 2 source PDFs.
    """
    if PdfWriter is None:
        logger.warning("pypdf is not installed. Skipping unit PDF merging.")
        return None

    unit_dir = Path(unit_dir)
    if not unit_dir.is_dir():
        return None

    # Collect all non-combined PDFs
    source_pdfs = [
        f for f in unit_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".pdf" and not is_combined_pdf(f.name)
    ]

    if not source_pdfs:
        return None

    # Sort in lecture order
    sorted_pdfs = sorted(source_pdfs, key=natural_sort_key)

    out_name = f"{COMBINED_PREFIX} {unit_dir.name}.pdf"
    out_path = unit_dir / out_name
    tmp_path = unit_dir / f"{out_name}.tmp"

    writer = PdfWriter()
    merged_count = 0

    for pdf_path in sorted_pdfs:
        try:
            writer.append(str(pdf_path))
            merged_count += 1
        except Exception as e:
            logger.warning("Could not append %s to merged unit PDF: %s", pdf_path.name, e)

    if merged_count == 0:
        try:
            writer.close()
        except Exception:
            pass
        return None

    try:
        with open(tmp_path, "wb") as f:
            writer.write(f)
        writer.close()
        # Atomic replace
        if tmp_path.is_file():
            os.replace(tmp_path, out_path)
            logger.info("Successfully merged %d PDFs into %s", merged_count, out_path)
            return out_path
    except Exception as e:
        logger.error("Failed to write merged unit PDF %s: %s", out_path, e)
        if tmp_path.is_file():
            try:
                tmp_path.unlink()
            except OSError:
                pass
    finally:
        try:
            writer.close()
        except Exception:
            pass

    return None


def merge_all_units(slides_dir: Path, progress_callback=None) -> Dict[str, Any]:
    """
    Scans slides_dir for all unit folders and generates/updates merged PDFs for all units.
    """
    slides_dir = Path(slides_dir)
    if not slides_dir.is_dir():
        return {"units_processed": 0, "units_merged": 0, "merged_files": []}

    unit_dirs = []
    for root, dirs, files in os.walk(slides_dir):
        pdf_files = [f for f in files if f.lower().endswith(".pdf") and not is_combined_pdf(f)]
        if len(pdf_files) >= 1:
            unit_dirs.append(Path(root))

    units_merged = 0
    merged_files = []

    for i, u_dir in enumerate(unit_dirs, 1):
        if progress_callback:
            progress_callback({
                "unit": u_dir.name,
                "current": i,
                "total": len(unit_dirs)
            })
        out = merge_unit_folder(u_dir)
        if out:
            units_merged += 1
            merged_files.append(str(out))

    return {
        "units_processed": len(unit_dirs),
        "units_merged": units_merged,
        "merged_files": merged_files
    }


def update_courses_json_with_combined(metadata_path: Path, slides_dir: Path) -> int:
    """
    Ensures courses.json contains a class_no: 0 entry for every combined unit PDF.
    """
    metadata_path = Path(metadata_path)
    slides_dir = Path(slides_dir)
    if not metadata_path.is_file():
        return 0

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("Could not read courses metadata: %s", e)
        return 0

    changed = False
    added_count = 0

    for sem_name, subjects in data.items():
        if not isinstance(subjects, dict):
            continue
        for subj_name, subj_info in subjects.items():
            if not isinstance(subj_info, dict) or "units" not in subj_info:
                continue
            for unit_name, classes in subj_info["units"].items():
                if not isinstance(classes, list):
                    continue

                subj_dir = clean_name(subj_name, 70)
                unit_dir = clean_name(unit_name, 60)
                folder = slides_dir / sem_name / subj_dir / unit_dir

                combined_file = folder / f"{COMBINED_PREFIX} {unit_dir}.pdf"
                if not combined_file.is_file():
                    # Check any combined PDF in folder
                    for candidate in folder.glob(f"{COMBINED_PREFIX}*.pdf"):
                        combined_file = candidate
                        break

                if combined_file.is_file():
                    try:
                        rel_path = combined_file.relative_to(slides_dir)
                    except ValueError:
                        rel_path = combined_file
                    rel_str = str(rel_path).replace("\\", "/")

                    existing_0 = next((c for c in classes if c.get("class_no") == 0), None)
                    if existing_0:
                        existing_0["files"] = [{
                            "name": combined_file.name,
                            "path": rel_str,
                            "type": "pdf"
                        }]
                    else:
                        classes.insert(0, {
                            "class_no": 0,
                            "title": f"📚 All Lectures Combined ({unit_name})",
                            "files": [{
                                "name": combined_file.name,
                                "path": rel_str,
                                "type": "pdf"
                            }]
                        })
                        added_count += 1
                        changed = True

    if changed:
        try:
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info("Updated courses.json with %d combined unit entries.", added_count)
        except Exception as e:
            logger.warning("Could not write updated courses.json: %s", e)

    return added_count
