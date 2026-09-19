"""Generate the three synthetic students from spec section 8.

Run with: .venv/Scripts/python.exe scripts/generate_fixtures.py

Writes, per student, under fixtures/students/<student_id>/:
  documents/<doc_type>.jpg   - a Pillow-rendered mock of the document
  ground_truth.json          - the exact field values baked into the images

...and fixtures/students/students.json, a manifest of all three.

ground_truth.json exists because phases 2-3 test cross-checking and
formatting logic directly against known field values — no OCR/extraction
agent exists yet (that's phase 5). fixtures_loader.py turns ground truth
into ExtractedDocument objects for those tests.

Every student is entirely fictional. No real Aadhaar numbers, no real bank
details, no real people.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "students"

FONT_REGULAR = "C:/Windows/Fonts/arial.ttf"
FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"

PAGE_SIZE = (1240, 1754)  # ~A4 at 150 DPI


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _display_date(iso_date: str) -> str:
    """ISO (ground_truth.json's internal format) -> DD/MM/YYYY (what
    actually gets rendered on the document, matching Indian convention)."""
    return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d/%m/%Y")


def render_certificate(
    out_path: Path,
    *,
    title: str,
    issuing_authority: str,
    certificate_no: str,
    fields: dict[str, str],
) -> None:
    """A plain, obviously-synthetic government-certificate-style mockup."""
    title_font = _font(FONT_BOLD, 34)
    authority_font = _font(FONT_REGULAR, 22)
    label_font = _font(FONT_BOLD, 26)
    value_font = _font(FONT_REGULAR, 26)
    watermark_font = _font(FONT_BOLD, 46)

    # Watermark first, as a background layer — then all real text is drawn
    # opaque black on top of it. Compositing the watermark *over* finished
    # text (the original approach) subtly blended its red tint into black
    # glyph edges, which was enough to confuse OCR word-spacing on some
    # lines (confirmed: it merged "Priya Ramesh Nair" into one token on
    # priya_nair's marksheet; raising font size didn't help since the
    # watermark, not legibility, was the cause). Drawing it first means the
    # opaque text fully overwrites the tint at every glyph pixel — the
    # watermark stays visible everywhere else, at full clarity for OCR.
    watermark = Image.new("RGBA", PAGE_SIZE, (0, 0, 0, 0))
    wdraw = ImageDraw.Draw(watermark)
    wdraw.text(
        (PAGE_SIZE[0] / 2, PAGE_SIZE[1] / 2),
        "SYNTHETIC — NOT A REAL DOCUMENT",
        font=watermark_font,
        fill=(200, 30, 30, 90),
        anchor="mm",
    )
    watermark = watermark.rotate(30, expand=False, center=(PAGE_SIZE[0] / 2, PAGE_SIZE[1] / 2))
    img = Image.alpha_composite(Image.new("RGBA", PAGE_SIZE, "white"), watermark).convert("RGB")
    draw = ImageDraw.Draw(img)

    margin = 90
    draw.rectangle(
        [margin - 30, margin - 30, PAGE_SIZE[0] - margin + 30, PAGE_SIZE[1] - margin + 30],
        outline="black",
        width=3,
    )

    y = margin
    draw.text((PAGE_SIZE[0] / 2, y), issuing_authority, font=authority_font, fill="black", anchor="ma")
    y += 40
    draw.text((PAGE_SIZE[0] / 2, y), title, font=title_font, fill="black", anchor="ma")
    y += 60
    draw.text((PAGE_SIZE[0] / 2, y), f"Certificate No: {certificate_no}", font=value_font, fill="black", anchor="ma")
    y += 70
    draw.line([(margin, y), (PAGE_SIZE[0] - margin, y)], fill="black", width=1)
    y += 40

    for label, value in fields.items():
        draw.text((margin, y), f"{label}:", font=label_font, fill="black")
        draw.text((margin + 320, y), str(value), font=value_font, fill="black")
        # 60px row spacing, not 48 — tighter spacing was enough to make
        # rapidocr occasionally merge adjacent words on some rows (e.g.
        # "Priya Ramesh Nair" -> "PriyaRameshNair"), inconsistently and
        # unpredictably depending on the page's total row count. Confirmed
        # empirically: more vertical clearance between rows fixes it
        # reliably; font size alone did not.
        y += 72

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Both of these mattered, tested independently and together: at the
    # original 48px row spacing / quality=90, rapidocr would occasionally
    # merge adjacent words on some rows (e.g. "Priya Ramesh Nair" ->
    # "PriyaRameshNair") depending on the full page's layout — lossless
    # PNG read every row correctly, which pointed at JPEG's lossy
    # compression blurring word-boundary pixels just enough to tip
    # rapidocr's detector over its merge threshold. quality=95 alone
    # fixed it in isolation but not combined with tighter spacing; more
    # vertical clearance between rows (72px) plus quality=95 together
    # fixed every document across all three students (verified below).
    img.save(out_path, "JPEG", quality=95)


def render_signature(out_path: Path, name: str) -> None:
    img = Image.new("RGB", (400, 150), "white")
    draw = ImageDraw.Draw(img)
    font = _font(FONT_REGULAR, 30)
    initials = "".join(part[0] for part in name.split()[:3])
    draw.text((30, 50), initials, font=font, fill="navy")
    draw.line([(20, 110), (370, 100), (60, 95), (350, 105)], fill="navy", width=2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=90)


def render_photo(out_path: Path, *, oversized: bool) -> tuple[int, int]:
    """A synthetic passport-style headshot mock, not a real photo of anyone."""
    if oversized:
        size = (2200, 2900)  # far above the ~276x354px portal spec
    else:
        size = (600, 800)

    img = Image.new("RGB", size, (210, 225, 235))
    draw = ImageDraw.Draw(img)
    w, h = size
    draw.ellipse([w * 0.28, h * 0.15, w * 0.72, h * 0.55], fill=(200, 170, 140))
    draw.ellipse([w * 0.2, h * 0.55, w * 0.8, h * 1.05], fill=(60, 60, 90))

    if oversized:
        # blended noise pushes JPEG entropy up so the source lands near a
        # realistic ~2MB phone-camera-photo size (spec section 8), not a
        # near-empty flat-colour file
        noise = Image.effect_noise(size, 40).convert("RGB")
        img = Image.blend(img, noise, alpha=0.20)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    quality = 92 if oversized else 90
    img.save(out_path, "JPEG", quality=quality)
    return size


STUDENTS = [
    {
        "student_id": "priya_nair",
        "scenario": "clean — valid documents, photo needs reformatting",
        "canonical_name": "Priya Ramesh Nair",
        "father_name": "Ramesh Nair",
        "dob": "12/03/2008",
        "address": "Kochi, Kerala",
        "documents": {
            "income_certificate": {
                "name": "Priya Ramesh Nair",
                "annual_income": "Rs. 1,85,000",
                "issue_date": "2026-04-10",
                "valid_until": "2027-04-09",
            },
            "caste_certificate": {
                "name": "Priya Ramesh Nair",
                "caste_category": "OBC",
                "issue_date": "2024-06-01",
                "valid_until": "2029-06-01",
            },
            "domicile_certificate": {
                "name": "Priya Ramesh Nair",
                "issue_date": "2023-01-15",
                "valid_until": "2033-01-15",
            },
            "marksheet": {
                "name": "Priya Ramesh Nair",
                "roll_no": "KL-2026-04471",
                "marks_percent": "88.4%",
                "issue_date": "2026-05-20",
                "valid_until": None,
            },
            "bank_passbook": {
                "name": "Priya Ramesh Nair",
                "account_no": "XXXXXXXX4821",
                "bank_name": "State Bank of India",
                "issue_date": "2022-08-11",
                "valid_until": None,
            },
        },
        "photo_oversized": True,
    },
    {
        "student_id": "aditya_sharma",
        "scenario": "name variance across documents — should read as likely_fine",
        "canonical_name": "Aditya Kumar Sharma",
        "father_name": "Rajesh Kumar Sharma",
        "dob": "22/11/2007",
        "address": "Lucknow, Uttar Pradesh",
        "documents": {
            "income_certificate": {
                "name": "Aditya Kumar Sharma",
                "annual_income": "Rs. 2,40,000",
                "issue_date": "2026-05-02",
                "valid_until": "2027-05-01",
            },
            "caste_certificate": {
                "name": "Aditya Kumar Sharma",
                "caste_category": "General",
                "issue_date": "2021-03-10",
                "valid_until": "2031-03-10",
            },
            "domicile_certificate": {
                # spec section 8: initial-heavy variant
                "name": "A. K. Sharma",
                "issue_date": "2020-07-01",
                "valid_until": "2030-07-01",
            },
            "marksheet": {
                # treated as the reference document — full canonical name
                "name": "Aditya Kumar Sharma",
                "roll_no": "UP-2026-11982",
                "marks_percent": "91.2%",
                "issue_date": "2026-05-18",
                "valid_until": None,
            },
            "bank_passbook": {
                # spec section 8: middle name omitted
                "name": "Aditya Sharma",
                "account_no": "XXXXXXXX7734",
                "bank_name": "Punjab National Bank",
                "issue_date": "2023-02-14",
                "valid_until": None,
            },
        },
        "photo_oversized": False,
    },
    {
        "student_id": "mohammed_irfan",
        "scenario": "real blockers — expiring income certificate + DOB day/month collision",
        "canonical_name": "Mohammed Irfan Sheikh",
        "father_name": "Abdul Sheikh",
        "dob": "05/06/2007",
        "address": "Bhopal, Madhya Pradesh",
        "documents": {
            "income_certificate": {
                "name": "Mohammed Irfan Sheikh",
                "dob": "05/06/2007",
                "annual_income": "Rs. 1,10,000",
                "issue_date": "2025-09-20",
                # 11 days before the fixture scheme deadline of 2026-09-30
                # (see fixtures_loader.SCHEME_DEADLINE)
                "valid_until": "2026-09-19",
            },
            "caste_certificate": {
                "name": "Mohammed Irfan Sheikh",
                "dob": "05/06/2007",
                "caste_category": "OBC",
                "issue_date": "2022-01-05",
                "valid_until": "2032-01-05",
            },
            "domicile_certificate": {
                "name": "Mohammed Irfan Sheikh",
                # transposed day/month relative to every other document
                "dob": "06/05/2007",
                "issue_date": "2019-11-11",
                "valid_until": "2029-11-11",
            },
            "marksheet": {
                # the reference document for comparisons
                "name": "Mohammed Irfan Sheikh",
                "dob": "05/06/2007",
                "roll_no": "MP-2026-33012",
                "marks_percent": "76.8%",
                "issue_date": "2026-05-25",
                "valid_until": None,
            },
            "bank_passbook": {
                "name": "Mohammed Irfan Sheikh",
                "dob": "05/06/2007",
                "account_no": "XXXXXXXX2290",
                "bank_name": "Bank of Baroda",
                "issue_date": "2021-09-30",
                "valid_until": None,
            },
        },
        "photo_oversized": False,
    },
]

DOC_TITLES = {
    "income_certificate": ("INCOME CERTIFICATE", "Office of the Tehsildar"),
    "caste_certificate": ("CASTE CERTIFICATE", "Office of the District Magistrate"),
    "domicile_certificate": ("DOMICILE CERTIFICATE", "Office of the District Magistrate"),
    "marksheet": ("MARKSHEET", "Board of Secondary Education"),
    "bank_passbook": ("BANK PASSBOOK — KYC PAGE", "Nationalised Bank of India (fictional)"),
}


def generate() -> None:
    manifest = []

    for student in STUDENTS:
        student_dir = FIXTURES_DIR / student["student_id"]
        docs_dir = student_dir / "documents"
        ground_truth: dict = {
            "student_id": student["student_id"],
            "scenario": student["scenario"],
            "canonical_name": student["canonical_name"],
            "documents": {},
        }

        for i, (doc_type, doc_fields) in enumerate(student["documents"].items()):
            title, authority = DOC_TITLES[doc_type]
            fields = {
                "Name": doc_fields["name"],
                "Father's Name": student["father_name"],
                "DOB": doc_fields.get("dob", student["dob"]),
                "Address": student["address"],
            }
            for key, value in doc_fields.items():
                if key in {"name", "dob", "issue_date", "valid_until"}:
                    continue
                fields[key.replace("_", " ").title()] = value

            # issue_date/valid_until must actually appear on the document
            # image, not just in ground_truth.json — otherwise a real
            # OCR+LLM verifier (phase 5c) has no way to read them; a real
            # certificate always states its own validity.
            if doc_fields.get("issue_date"):
                fields["Date of Issue"] = _display_date(doc_fields["issue_date"])
            if doc_fields.get("valid_until"):
                fields["Valid Until"] = _display_date(doc_fields["valid_until"])

            out_path = docs_dir / f"{doc_type}.jpg"
            render_certificate(
                out_path,
                title=title,
                issuing_authority=authority,
                certificate_no=f"{doc_type[:3].upper()}-{2026000 + i}-{student['student_id'][:3].upper()}",
                fields=fields,
            )

            ground_truth["documents"][doc_type] = {
                "fields": {
                    "name": doc_fields["name"],
                    "father_name": student["father_name"],
                    "dob": doc_fields.get("dob", student["dob"]),
                },
                "issue_date": doc_fields["issue_date"],
                "valid_until": doc_fields["valid_until"],
                "source_path": str(out_path.relative_to(FIXTURES_DIR.parent.parent)),
            }

        signature_path = docs_dir / "signature.jpg"
        render_signature(signature_path, student["canonical_name"])
        ground_truth["documents"]["signature"] = {
            "fields": {"name": student["canonical_name"]},
            "issue_date": None,
            "valid_until": None,
            "source_path": str(signature_path.relative_to(FIXTURES_DIR.parent.parent)),
        }

        photo_path = docs_dir / "photo.jpg"
        dims = render_photo(photo_path, oversized=student["photo_oversized"])
        ground_truth["documents"]["photo"] = {
            "fields": {"name": student["canonical_name"]},
            "issue_date": None,
            "valid_until": None,
            "source_path": str(photo_path.relative_to(FIXTURES_DIR.parent.parent)),
            "note": f"rendered at {dims[0]}x{dims[1]}px"
            + (" — deliberately oversized for the formatter test" if student["photo_oversized"] else ""),
        }

        gt_path = student_dir / "ground_truth.json"
        gt_path.write_text(json.dumps(ground_truth, indent=2), encoding="utf-8")

        manifest.append(
            {
                "student_id": student["student_id"],
                "canonical_name": student["canonical_name"],
                "scenario": student["scenario"],
            }
        )
        print(f"generated {student['student_id']}: {docs_dir} ({photo_path.stat().st_size / 1024:.0f} KB photo)")

    (FIXTURES_DIR / "students.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote manifest for {len(manifest)} students to {FIXTURES_DIR / 'students.json'}")


if __name__ == "__main__":
    generate()
