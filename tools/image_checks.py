"""Deterministic checks for photo/signature documents. No LLM.

Unlike the five certificate-style verifiers, a photo or signature has no
text fields to extract — there's no OCR step, nothing for an LLM to read.
What matters is whether the FILE ITSELF is fit for purpose: right
dimensions/format/size against the scheme's spec, and not blank or
corrupt. fields on the resulting ExtractedDocument therefore holds file
metadata (dimensions_px, format, size_kb, any issues found), not name/dob —
cross_checker's name/dob comparisons naturally skip these documents since
they never have a "name" field.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageStat, UnidentifiedImageError

from contracts import ExtractedDocument, RequiredDoc

# Below this stddev (0-255 grayscale), an image is treated as blank/near-
# uniform (a solid colour rectangle, a failed render, a corrupted capture)
# rather than a real photo or signature.
BLANK_STDDEV_THRESHOLD = 3.0

# PIL's Image.format is always "JPEG", regardless of whether the file's
# extension (and therefore a RequiredDoc.file_formats entry) says "jpg" or
# "jpeg" — treat them as the same format when comparing.
_FORMAT_ALIASES = {"jpg": "jpeg"}


def _normalize_format(fmt: str) -> str:
    fmt = fmt.lower()
    return _FORMAT_ALIASES.get(fmt, fmt)


def _blank_or_corrupt_reason(path: Path) -> str | None:
    """None if the file opens and isn't blank; otherwise a reason string."""
    try:
        with Image.open(path) as img:
            img.verify()
    except (UnidentifiedImageError, OSError) as exc:
        return f"file could not be opened or decoded: {exc}"

    try:
        with Image.open(path) as img:
            stddev = ImageStat.Stat(img.convert("L")).stddev[0]
    except (UnidentifiedImageError, OSError) as exc:
        return f"file could not be opened or decoded: {exc}"

    if stddev < BLANK_STDDEV_THRESHOLD:
        return f"image appears blank or near-uniform (grayscale stddev={stddev:.2f})"

    return None


def check_image_document(
    doc_type: str,
    source_path: Path,
    required: RequiredDoc | None = None,
) -> ExtractedDocument:
    """Dimensions, format, file size, and a blank/corrupt check for a
    photo or signature file, compared against `required` if given."""
    problem = _blank_or_corrupt_reason(source_path)
    issues: list[str] = []
    fields: dict[str, str] = {}

    if problem:
        issues.append(problem)
        return ExtractedDocument(
            doc_type=doc_type,
            source_path=source_path,
            fields={"issues": problem},
            issue_date=None,
            valid_until=None,
            extraction_confidence=0.0,
        )

    with Image.open(source_path) as img:
        dimensions = img.size
        file_format = (img.format or "").lower()
    size_kb = source_path.stat().st_size / 1024

    fields["dimensions_px"] = f"{dimensions[0]}x{dimensions[1]}"
    fields["format"] = file_format
    fields["size_kb"] = f"{size_kb:.1f}"

    confidence = 1.0
    if required is not None:
        allowed_formats = {_normalize_format(f) for f in required.file_formats}
        if required.file_formats and _normalize_format(file_format) not in allowed_formats:
            issues.append(f"format {file_format!r} not in required {required.file_formats}")
            confidence -= 0.3
        if required.max_size_kb is not None and size_kb > required.max_size_kb:
            issues.append(f"{size_kb:.1f}KB exceeds the {required.max_size_kb}KB cap")
            confidence -= 0.3
        if required.dimensions_px is not None and tuple(dimensions) != tuple(required.dimensions_px):
            issues.append(f"dimensions {dimensions} do not match required {required.dimensions_px}")
            confidence -= 0.3

    if issues:
        fields["issues"] = "; ".join(issues)

    return ExtractedDocument(
        doc_type=doc_type,
        source_path=source_path,
        fields=fields,
        issue_date=None,
        valid_until=None,
        extraction_confidence=max(0.0, round(confidence, 2)),
    )


def check_photo(source_path: Path, required: RequiredDoc | None = None) -> ExtractedDocument:
    return check_image_document("photo", source_path, required)


def check_signature(source_path: Path, required: RequiredDoc | None = None) -> ExtractedDocument:
    return check_image_document("signature", source_path, required)


IMAGE_CHECKS = {
    "photo": check_photo,
    "signature": check_signature,
}
