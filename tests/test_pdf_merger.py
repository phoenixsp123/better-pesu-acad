"""
Tests for PDF Unit Merger and Automatic Sync Merging.
"""

import json
import tempfile
from pathlib import Path
import pytest
from pypdf import PdfWriter, PdfReader

from backend.jobs.pdf_merger import (
    natural_sort_key,
    is_combined_pdf,
    merge_unit_folder,
    merge_all_units,
    update_courses_json_with_combined,
    COMBINED_PREFIX
)


def create_dummy_pdf(path: Path, num_pages: int = 1):
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        writer.write(f)
    writer.close()


def test_natural_sort_key():
    files = [
        Path("10 - L10.pdf"),
        Path("01 - L1.pdf"),
        Path("02 - L2.pdf"),
        Path("L3_notes.pdf")
    ]
    sorted_files = sorted(files, key=natural_sort_key)
    names = [f.name for f in sorted_files]
    assert names[0] == "01 - L1.pdf"
    assert names[1] == "02 - L2.pdf"
    assert names[2] == "L3_notes.pdf"
    assert names[3] == "10 - L10.pdf"


def test_is_combined_pdf():
    assert is_combined_pdf("00 - [Combined] Unit 1.pdf") is True
    assert is_combined_pdf("[Combined] Unit 2.pdf") is True
    assert is_combined_pdf("01 - Lecture 1.pdf") is False


def test_merge_unit_folder():
    with tempfile.TemporaryDirectory() as tmpdir:
        unit_dir = Path(tmpdir) / "Unit 1 - Basics"
        unit_dir.mkdir()

        f1 = unit_dir / "01 - L1.pdf"
        f2 = unit_dir / "02 - L2.pdf"
        create_dummy_pdf(f1, num_pages=2)
        create_dummy_pdf(f2, num_pages=3)

        out = merge_unit_folder(unit_dir)
        assert out is not None
        assert out.is_file()
        assert out.name == f"{COMBINED_PREFIX} Unit 1 - Basics.pdf"

        # Verify page count
        reader = PdfReader(str(out))
        assert len(reader.pages) == 5

        # If a 3rd PDF is added (simulating sync), merge_unit_folder updates it
        f3 = unit_dir / "03 - L3.pdf"
        create_dummy_pdf(f3, num_pages=4)

        out2 = merge_unit_folder(unit_dir)
        assert out2 is not None
        reader2 = PdfReader(str(out2))
        assert len(reader2.pages) == 9  # 2 + 3 + 4


def test_merge_all_units_and_update_metadata():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        slides_dir = root / "slides"
        u1 = slides_dir / "Sem-3" / "CS101" / "Unit 1"
        u2 = slides_dir / "Sem-3" / "CS101" / "Unit 2"
        create_dummy_pdf(u1 / "01 - a.pdf", num_pages=1)
        create_dummy_pdf(u1 / "02 - b.pdf", num_pages=1)
        create_dummy_pdf(u2 / "01 - c.pdf", num_pages=2)
        create_dummy_pdf(u2 / "02 - d.pdf", num_pages=2)

        courses_file = root / "courses.json"
        sample_meta = {
            "Sem-3": {
                "CS101": {
                    "title": "CS101",
                    "units": {
                        "Unit 1": [
                            {"class_no": 1, "title": "A", "files": [{"name": "01 - a.pdf", "path": "Sem-3/CS101/Unit 1/01 - a.pdf", "type": "pdf"}]}
                        ],
                        "Unit 2": [
                            {"class_no": 1, "title": "C", "files": [{"name": "01 - c.pdf", "path": "Sem-3/CS101/Unit 2/01 - c.pdf", "type": "pdf"}]}
                        ]
                    }
                }
            }
        }
        courses_file.write_text(json.dumps(sample_meta), encoding="utf-8")

        res = merge_all_units(slides_dir)
        assert res["units_merged"] == 2

        added = update_courses_json_with_combined(courses_file, slides_dir)
        assert added == 2

        updated_data = json.loads(courses_file.read_text(encoding="utf-8"))
        u1_classes = updated_data["Sem-3"]["CS101"]["units"]["Unit 1"]
        assert u1_classes[0]["class_no"] == 0
        assert "[Combined]" in u1_classes[0]["files"][0]["name"]
