"""Generate the synthetic scheme notification PDFs for phase 4.

Run with: .venv/Scripts/python.exe scripts/generate_scheme_pdfs.py

Writes to fixtures/schemes/:
  scheme_a_postmatric.pdf - 3 pages, prose-heavy, format specs in a
                             page-3 annexure table, 7 documents, deadline
                             2026-09-30 (must match fixtures_loader.SCHEME_DEADLINE)
  scheme_b_merit.pdf      - 2 pages, a genuinely different requirement set:
                             3 documents, 2 fields scheme A doesn't have, a
                             different deadline, and one deliberately vague
                             format clause (no numbers) for bank_passbook
  garbage_scan.pdf        - a blank page with no extractable text, to
                             exercise the extractor's "unreadable input"
                             path without needing a real OCR failure

Every page is watermarked SYNTHETIC. Every scheme, student, and detail here
is fictional.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "schemes"

styles = getSampleStyleSheet()
BODY = ParagraphStyle("KagazBody", parent=styles["Normal"], fontSize=11, leading=16, spaceAfter=10)
H1 = ParagraphStyle("KagazH1", parent=styles["Heading1"], fontSize=16, spaceAfter=14)
H2 = ParagraphStyle("KagazH2", parent=styles["Heading2"], fontSize=13, spaceAfter=10)


def _watermark(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 46)
    canvas.setFillColor(colors.Color(0.8, 0.15, 0.15, alpha=0.18))
    canvas.translate(A4[0] / 2, A4[1] / 2)
    canvas.rotate(35)
    canvas.drawCentredString(0, 0, "SYNTHETIC — NOT A REAL DOCUMENT")
    canvas.restoreState()


def _build(filename: str, story: list) -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(FIXTURES_DIR / filename),
        pagesize=A4,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
    )
    doc.build(story, onFirstPage=_watermark, onLaterPages=_watermark)
    print(f"wrote {FIXTURES_DIR / filename}")


def generate_scheme_a() -> None:
    story = [
        Paragraph("Post-Matric Scholarship for Minority Communities — 2026-27", H1),
        Paragraph(
            "The Directorate of Minority Welfare invites online applications from students "
            "belonging to notified minority communities who are pursuing post-matriculation "
            "courses at a recognised institution during the academic year 2026-27.",
            BODY,
        ),
        Paragraph("Eligibility and Documents Required", H2),
        Paragraph(
            "Applicants must submit an Income Certificate issued by the competent revenue "
            "authority, a Caste Certificate, and a Domicile Certificate establishing residence "
            "in the state. In addition, applicants must upload their most recent Marksheet and "
            "a copy of their Bank Passbook reflecting the account into which the scholarship "
            "amount will be disbursed. A recent Photograph and a Specimen Signature must also "
            "be uploaded as part of the online application.",
            BODY,
        ),
        Paragraph(
            "The last date for submission of online applications is 30th September 2026. "
            "Applications received after this date will not be considered under any "
            "circumstances, regardless of the reason for delay.",
            BODY,
        ),
        PageBreak(),
        Paragraph("Particulars Required on the Application Form", H2),
        Paragraph(
            "The online application form requires applicants to furnish the following "
            "particulars: Full Name (as per Aadhaar), Father's/Guardian's Name, Date of Birth, "
            "Aadhaar Number, Bank Account Number, IFSC Code, Annual Family Income, and "
            "Course/Institution Details.",
            BODY,
        ),
        Paragraph(
            "Incomplete applications, or applications in which the particulars above do not "
            "match the uploaded supporting documents, are liable to be rejected without "
            "further notice. Applicants are strongly advised to verify every field before "
            "final submission.",
            BODY,
        ),
        PageBreak(),
        Paragraph("Annexure-I: Format Specifications for Uploaded Documents", H2),
        Paragraph(
            "All documents must be uploaded strictly in the formats and size limits given "
            "below. Uploads outside these limits will be rejected automatically by the portal.",
            BODY,
        ),
        Spacer(1, 8),
        Table(
            [
                ["Document", "Accepted Format", "Max File Size", "Dimensions"],
                ["Photograph", "JPG, JPEG", "50 KB", "276 x 354 px (3.5cm x 4.5cm @ 200 DPI)"],
                ["Specimen Signature", "JPG, JPEG", "20 KB", "276 x 118 px (3.5cm x 1.5cm @ 200 DPI)"],
                ["Income Certificate", "PDF", "200 KB", "-"],
                ["Caste Certificate", "PDF", "200 KB", "-"],
                ["Domicile Certificate", "PDF", "200 KB", "-"],
                ["Marksheet", "PDF", "200 KB", "-"],
                ["Bank Passbook (first page)", "PDF, JPG", "150 KB", "-"],
            ],
            colWidths=[5.5 * cm, 3.2 * cm, 2.8 * cm, 5.5 * cm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            ),
        ),
    ]
    _build("scheme_a_postmatric.pdf", story)


def generate_scheme_b() -> None:
    story = [
        Paragraph("State Merit Scholarship — 2026", H1),
        Paragraph(
            "This scholarship is awarded purely on academic merit to students who have scored "
            "in the top percentile of their qualifying board examination. It is administered "
            "directly by the State Directorate of Higher Education.",
            BODY,
        ),
        Paragraph("Documents Required", H2),
        Paragraph(
            "Applicants must submit their most recent Marksheet, a Bank Passbook copy for "
            "disbursal of the award, and a recent Photograph as part of the online application. "
            "No other supporting documents are required for this scheme.",
            BODY,
        ),
        Paragraph(
            "The last date for submission is 15th October 2026.",
            BODY,
        ),
        Paragraph("Particulars Required on the Application Form", H2),
        Paragraph(
            "The application form requires: Full Name (as per Aadhaar), Date of Birth, Merit "
            "Rank / Percentile in Qualifying Examination, Mobile Number Linked to Aadhaar, Bank "
            "Account Number, and IFSC Code.",
            BODY,
        ),
        PageBreak(),
        Paragraph("Format Specifications", H2),
        Paragraph(
            "<b>Photograph:</b> JPG or JPEG format, maximum 30 KB, dimensions 200 x 230 pixels.",
            BODY,
        ),
        Paragraph(
            "<b>Marksheet:</b> PDF format, maximum 100 KB.",
            BODY,
        ),
        Paragraph(
            "<b>Bank Passbook:</b> All supporting documents must be uploaded in the prescribed "
            "format as specified by the Directorate.",
            BODY,
        ),
    ]
    _build("scheme_b_merit.pdf", story)


def generate_garbage_scan() -> None:
    # A page with no extractable text at all - the closest a text-based
    # generator can get to simulating a failed/blank scan without an image
    # rasteriser. pdfplumber's extract_text() returns "" or near-empty for
    # this, which is exactly the input the extractor's guard clause exists
    # to handle.
    story = [Spacer(1, 5 * cm)]
    _build("garbage_scan.pdf", story)


if __name__ == "__main__":
    generate_scheme_a()
    generate_scheme_b()
    generate_garbage_scan()
