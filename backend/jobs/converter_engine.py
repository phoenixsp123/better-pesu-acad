"""
PowerPoint to PDF conversion engine for Better PESU Acad.
Uses headless LibreOffice with graceful fallback, timeout management,
progress emission, and metadata updating.
"""

from __future__ import annotations

import os
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.config import find_libreoffice

logger = logging.getLogger("betterpesu.converter")


class ConverterEngine:
    def __init__(self, slides_dir: Path | str, metadata_file: Path | str):
        self.slides_dir = Path(slides_dir)
        self.metadata_file = Path(metadata_file)
        self.libreoffice = find_libreoffice()

    def is_available(self) -> bool:
        return self.libreoffice is not None

    def convert_pptx(self, pptx_path: Path) -> Optional[Path]:
        """Convert a single PPT/PPTX file to PDF in the same folder."""
        if not self.libreoffice:
            logger.warning("LibreOffice not available for conversion of %s", pptx_path)
            return None

        pptx_path = pptx_path.resolve()
        if not pptx_path.is_file():
            return None

        folder = pptx_path.parent
        pdf_path = pptx_path.with_suffix(".pdf")

        if pdf_path.is_file():
            # Already converted; remove leftover PPTX
            try:
                pptx_path.unlink()
            except OSError:
                pass
            return pdf_path

        try:
            cmd = [
                self.libreoffice,
                "--headless",
                "--convert-to", "pdf",
                "--outdir", str(folder),
                str(pptx_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0 and pdf_path.is_file():
                try:
                    pptx_path.unlink()
                except OSError:
                    pass
                return pdf_path
            else:
                logger.error("LibreOffice error on %s: %s", pptx_path.name, result.stderr or result.stdout)
                return None
        except Exception as e:
            logger.exception("Failed to convert %s: %s", pptx_path.name, e)
            return None

    def update_metadata(self, selected_semester: Optional[str] = None, selected_subject_id: Optional[str] = None) -> int:
        """Update courses.json to point PPTX entries to newly created PDFs."""
        if not self.metadata_file.is_file():
            return 0

        try:
            with open(self.metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception as e:
            logger.error("Could not read metadata for update: %s", e)
            return 0

        updated = 0
        for semester_name, semester in metadata.items():
            if selected_semester and semester_name != selected_semester:
                continue
            for subject in semester.values():
                if selected_subject_id and str(subject.get("id")) != str(selected_subject_id):
                    continue
                for classes in subject.get("units", {}).values():
                    for class_data in classes:
                        for file_item in class_data.get("files", []):
                            ftype = str(file_item.get("type", "")).lower()
                            fname = str(file_item.get("name", "")).lower()
                            if ftype != "pptx" and not fname.endswith(".pptx"):
                                continue

                            old_path = file_item.get("path", "")
                            # Resolve path
                            if os.path.isabs(old_path):
                                full_p = Path(old_path)
                            else:
                                full_p = self.slides_dir / old_path

                            pdf_p = full_p.with_suffix(".pdf")
                            if pdf_p.is_file():
                                file_item["name"] = pdf_p.name
                                try:
                                    rel = pdf_p.relative_to(self.slides_dir)
                                except ValueError:
                                    rel = Path(old_path).with_suffix(".pdf")
                                file_item["path"] = str(rel).replace("\\", "/")
                                file_item["type"] = "pdf"
                                updated += 1

        if updated > 0:
            tmp = str(self.metadata_file) + ".part"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.metadata_file)
            logger.info("Updated %d files in metadata to PDF references", updated)

        return updated

    def run_conversion(
        self,
        selected_semester: Optional[str] = None,
        selected_subject_id: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None
    ) -> Dict[str, Any]:
        """
        Scan slides directory for PPTX files and convert them.
        Returns summary stats.
        """
        if not self.is_available():
            logger.warning("LibreOffice is not installed. Skipping PPTX to PDF conversion.")
            return {"converted": 0, "failed": 0, "total": 0, "available": False}

        scan_dir = self.slides_dir
        if selected_semester and not selected_subject_id:
            sem_dir = self.slides_dir / selected_semester
            if sem_dir.is_dir():
                scan_dir = sem_dir

        pptx_files = []
        for root, _, files in os.walk(scan_dir):
            for file in files:
                if file.lower().endswith((".pptx", ".ppt")):
                    pptx_files.append(Path(root) / file)

        total = len(pptx_files)
        if progress_callback:
            progress_callback({"event": "conversion_plan", "total": total})

        converted = 0
        failed = 0

        for idx, pptx in enumerate(pptx_files, 1):
            if is_cancelled and is_cancelled():
                logger.info("Conversion cancelled by user")
                break

            pdf = self.convert_pptx(pptx)
            if pdf:
                converted += 1
            else:
                failed += 1

            if progress_callback:
                progress_callback({
                    "event": "conversion_file",
                    "done": idx,
                    "total": total,
                    "converted": converted,
                    "failed": failed,
                    "current_file": pptx.name
                })

        # Update metadata records
        self.update_metadata(selected_semester, selected_subject_id)

        return {"converted": converted, "failed": failed, "total": total, "available": True}
