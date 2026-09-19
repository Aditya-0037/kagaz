"""Deterministic image/PDF formatting tools (spec section 6.4). No LLM calls.

Every function here reads from source_path and writes to dest_path — the
original is never touched. Every conversion returns a ConversionLog with
before/after dimensions and file size, and prints it (that log line is a
demo beat per the spec).
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import img2pdf
from PIL import Image

MIN_JPEG_QUALITY = 40  # readability floor: never compress past this


@dataclass(frozen=True)
class ConversionLog:
    source_path: Path
    dest_path: Path
    before_dimensions_px: tuple[int, int] | None
    after_dimensions_px: tuple[int, int] | None
    before_size_kb: float
    after_size_kb: float
    quality_used: int | None
    output_format: str

    def __str__(self) -> str:
        dims = ""
        if self.before_dimensions_px and self.after_dimensions_px:
            bw, bh = self.before_dimensions_px
            aw, ah = self.after_dimensions_px
            dims = f", {bw}x{bh}px -> {aw}x{ah}px"
        quality = f", q={self.quality_used}" if self.quality_used is not None else ""
        return (
            f"[formatter] {self.source_path.name} -> {self.dest_path.name}: "
            f"{self.before_size_kb:.1f}KB -> {self.after_size_kb:.1f}KB{dims} "
            f"({self.output_format}{quality})"
        )


def cm_to_px(cm: float, dpi: int = 200) -> int:
    """Portal specs are usually given in cm @ some DPI; convert to pixels."""
    return round(cm / 2.54 * dpi)


def _resize_and_pad(
    image: Image.Image,
    target_dims: tuple[int, int],
    background: tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """Scale to fit inside target_dims preserving aspect ratio, then pad
    (never distort) onto a canvas of exactly target_dims."""
    target_w, target_h = target_dims
    src_w, src_h = image.size
    scale = min(target_w / src_w, target_h / src_h)
    new_w, new_h = max(1, round(src_w * scale)), max(1, round(src_h * scale))

    resized = image.convert("RGB").resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGB", target_dims, background)
    canvas.paste(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2))
    return canvas


def _compress_jpeg_under(
    image: Image.Image, max_size_kb: int, min_quality: int = MIN_JPEG_QUALITY
) -> tuple[bytes, int]:
    """Iteratively reduce JPEG quality until under max_size_kb, never going
    below min_quality. If even the quality floor is over budget, returns
    the floor-quality bytes anyway rather than degrading further."""
    quality = 95
    data = b""
    while True:
        buf = BytesIO()
        image.save(buf, "JPEG", quality=quality)
        data = buf.getvalue()
        if len(data) <= max_size_kb * 1024 or quality <= min_quality:
            return data, quality
        quality -= 5


def format_photo(
    source_path: Path,
    dest_path: Path,
    dimensions_px: tuple[int, int],
    max_size_kb: int,
) -> ConversionLog:
    """Resize (pad, don't distort) to dimensions_px and compress under
    max_size_kb as a JPEG. Never modifies source_path."""
    before_size_kb = source_path.stat().st_size / 1024
    with Image.open(source_path) as img:
        before_dims = img.size
        canvas = _resize_and_pad(img, dimensions_px)

    data, quality = _compress_jpeg_under(canvas, max_size_kb)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(data)

    log = ConversionLog(
        source_path=source_path,
        dest_path=dest_path,
        before_dimensions_px=before_dims,
        after_dimensions_px=dimensions_px,
        before_size_kb=before_size_kb,
        after_size_kb=len(data) / 1024,
        quality_used=quality,
        output_format="JPEG",
    )
    print(log)
    return log


def convert_image_format(source_path: Path, dest_path: Path, file_format: str) -> ConversionLog:
    """Convert between jpg/jpeg/png without resizing."""
    pillow_format = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG"}[file_format.lower()]
    before_size_kb = source_path.stat().st_size / 1024

    with Image.open(source_path) as img:
        before_dims = img.size
        converted = img.convert("RGB" if pillow_format == "JPEG" else "RGBA")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        converted.save(dest_path, pillow_format)
        after_dims = converted.size

    after_size_kb = dest_path.stat().st_size / 1024
    log = ConversionLog(
        source_path=source_path,
        dest_path=dest_path,
        before_dimensions_px=before_dims,
        after_dimensions_px=after_dims,
        before_size_kb=before_size_kb,
        after_size_kb=after_size_kb,
        quality_used=None,
        output_format=pillow_format,
    )
    print(log)
    return log


def format_document_pdf(
    source_path: Path,
    dest_path: Path,
    max_size_kb: int,
    min_quality: int = MIN_JPEG_QUALITY,
) -> ConversionLog:
    """Wrap a scanned document image into a PDF under max_size_kb, by
    compressing the source image before wrapping (img2pdf itself doesn't
    recompress) and iterating quality down if the PDF container pushes it
    back over budget."""
    before_size_kb = source_path.stat().st_size / 1024
    with Image.open(source_path) as img:
        before_dims = img.size
        rgb = img.convert("RGB")

    quality = 95
    pdf_bytes = b""
    while True:
        buf = BytesIO()
        rgb.save(buf, "JPEG", quality=quality)
        pdf_bytes = img2pdf.convert(buf.getvalue())
        if len(pdf_bytes) <= max_size_kb * 1024 or quality <= min_quality:
            break
        quality -= 5

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(pdf_bytes)

    log = ConversionLog(
        source_path=source_path,
        dest_path=dest_path,
        before_dimensions_px=before_dims,
        after_dimensions_px=rgb.size,
        before_size_kb=before_size_kb,
        after_size_kb=len(pdf_bytes) / 1024,
        quality_used=quality,
        output_format="PDF",
    )
    print(log)
    return log
