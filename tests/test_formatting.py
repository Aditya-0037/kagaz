from pathlib import Path

import pytest
from PIL import Image

from tools.formatting import (
    ConversionLog,
    cm_to_px,
    convert_image_format,
    format_document_pdf,
    format_photo,
)

PRIYA_PHOTO = Path(__file__).parent.parent / "fixtures" / "students" / "priya_nair" / "documents" / "photo.jpg"

# Typical Indian portal photo spec (spec section 6.4): 3.5x4.5cm @ 200 DPI, 20-50KB
PHOTO_DIMENSIONS_PX = (cm_to_px(3.5), cm_to_px(4.5))
PHOTO_MAX_KB = 50


def _require_fixture():
    if not PRIYA_PHOTO.exists():
        pytest.skip(
            f"{PRIYA_PHOTO} not generated yet — run "
            "`.venv/Scripts/python.exe scripts/generate_fixtures.py` first."
        )


def test_cm_to_px_matches_known_portal_spec():
    # 3.5cm @ 200dpi and 4.5cm @ 200dpi are the standard passport-photo cell
    assert cm_to_px(3.5, dpi=200) == 276
    assert cm_to_px(4.5, dpi=200) == 354


def test_source_photo_fixture_is_oversized():
    _require_fixture()
    size_kb = PRIYA_PHOTO.stat().st_size / 1024
    assert 1500 <= size_kb <= 3000  # ~2MB, per spec section 8


def test_format_photo_lands_under_size_cap_at_exact_dimensions(tmp_path):
    _require_fixture()
    dest = tmp_path / "photo_formatted.jpg"

    log = format_photo(PRIYA_PHOTO, dest, PHOTO_DIMENSIONS_PX, PHOTO_MAX_KB)

    assert isinstance(log, ConversionLog)
    assert log.after_dimensions_px == PHOTO_DIMENSIONS_PX
    assert log.after_size_kb <= PHOTO_MAX_KB
    assert log.after_size_kb > 0
    assert dest.exists()

    with Image.open(dest) as out:
        assert out.size == PHOTO_DIMENSIONS_PX


def test_format_photo_never_modifies_the_source(tmp_path):
    _require_fixture()
    before_bytes = PRIYA_PHOTO.read_bytes()
    format_photo(PRIYA_PHOTO, tmp_path / "out.jpg", PHOTO_DIMENSIONS_PX, PHOTO_MAX_KB)
    assert PRIYA_PHOTO.read_bytes() == before_bytes


def test_format_photo_does_not_distort_aspect_ratio(tmp_path):
    _require_fixture()
    # source fixture is 2200x2900 (0.759 w/h) vs target 276x354 (0.780 w/h):
    # close but not identical, so preserving aspect ratio must pad *some*
    # axis. Which axis depends on which dimension is scale-constrained, so
    # check all four corners rather than assume top/bottom vs left/right —
    # padding (on whichever axis it falls) always touches every corner,
    # while a distorted (stretched-to-fill) image would touch none.
    dest = tmp_path / "photo_formatted.jpg"
    format_photo(PRIYA_PHOTO, dest, PHOTO_DIMENSIONS_PX, PHOTO_MAX_KB)
    with Image.open(dest) as out:
        w, h = out.size
        corners = [
            out.getpixel((0, 0)),
            out.getpixel((w - 1, 0)),
            out.getpixel((0, h - 1)),
            out.getpixel((w - 1, h - 1)),
        ]
        assert all(all(channel > 230 for channel in px) for px in corners)


def test_format_photo_respects_quality_floor_on_tiny_budget(tmp_path):
    _require_fixture()
    dest = tmp_path / "tiny.jpg"
    # An unreasonably small budget must not be met by degrading past the floor
    log = format_photo(PRIYA_PHOTO, dest, PHOTO_DIMENSIONS_PX, max_size_kb=1)
    assert log.quality_used == 40


def test_convert_image_format_jpg_to_png(tmp_path):
    _require_fixture()
    dest = tmp_path / "photo.png"
    log = convert_image_format(PRIYA_PHOTO, dest, "png")
    assert log.output_format == "PNG"
    assert dest.exists()
    with Image.open(dest) as out:
        assert out.format == "PNG"


def test_format_document_pdf_lands_under_size_cap(tmp_path):
    _require_fixture()
    marksheet = PRIYA_PHOTO.parent / "marksheet.jpg"
    dest = tmp_path / "marksheet.pdf"
    log = format_document_pdf(marksheet, dest, max_size_kb=200)
    assert log.after_size_kb <= 200
    assert dest.exists()
    assert dest.read_bytes()[:5] == b"%PDF-"
