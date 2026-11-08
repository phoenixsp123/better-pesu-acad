"""
Regression tests verifying existing course data preservation and downloader utilities.
"""

import json
import tempfile
from pathlib import Path
import pytest

from backend.jobs.downloader_engine import clean_name, get_file_type, existing_file_check
from backend.jobs.converter_engine import ConverterEngine


def test_clean_name_and_file_types():
    assert clean_name('Lecture: 01 "OS Intro" / Unit 1') == 'Lecture- 01 -OS Intro- - Unit 1'
    assert clean_name('...') == 'untitled'
    assert get_file_type('notes.pdf') == 'pdf'
    assert get_file_type('slides.pptx') == 'pptx'
    assert get_file_type('archive.tar.gz') == 'gz'


def test_existing_file_check_duplicate_prevention():
    with tempfile.TemporaryDirectory() as tmpdir:
        folder = Path(tmpdir)
        pdf = folder / "slide_01.pdf"
        pdf.write_bytes(b"dummy pdf")

        pptx_candidate = folder / "slide_01.pptx"
        # Should detect that converted PDF already exists and skip PPTX download
        res = existing_file_check(pptx_candidate)
        assert res is not None
        assert "skipped" in res["status"]
        assert res["filename"] == "slide_01.pdf"

        # Check existing regular file
        res_direct = existing_file_check(pdf)
        assert res_direct is not None
        assert res_direct["status"] == "skipped"


def test_legacy_courses_json_structure():
    courses_path = Path(__file__).resolve().parent.parent / "pesu-notes" / "data" / "courses.json"
    if not courses_path.is_file():
        pytest.skip("Legacy courses.json not present")

    with open(courses_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Must contain Sem-3
    assert "Sem-3" in data
    sem3 = data["Sem-3"]
    assert len(sem3) > 0
    # Check subjects have id, code, title, units
    for sub in sem3.values():
        assert "id" in sub
        assert "code" in sub
        assert "title" in sub
        assert "units" in sub
