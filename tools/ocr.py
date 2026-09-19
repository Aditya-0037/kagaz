"""Document image -> text. The one place an OCR/vision decision happens
before verifiers can extract fields — see agents/verifiers/common.py.

Pluggable backend, selected by KAGAZ_OCR_BACKEND (defaulting to "vision"
when KAGAZ_MODEL_PROVIDER=vertex, else "rapidocr" — see _default_backend):

  rapidocr   - rapidocr-onnxruntime. Deterministic, no LLM. Pip-installable,
               no system binary, no network at inference time (model
               weights ship in the wheel). Verified on priya_nair's
               marksheet: >0.97 confidence on every field (tests/test_ocr.py).
  tesseract  - pytesseract, wraps the system `tesseract` binary. Deterministic,
               no LLM. Documented fallback if rapidocr's onnxruntime wheel
               doesn't install on some platform; not exercised in this
               environment since rapidocr worked on the first try.
  vision     - a real model call (not deterministic OCR): asks the current
               provider's model (model_provider.get_model()) to transcribe
               the image directly, replacing the OCR-then-LLM two-step with
               one multimodal call. Deliberately a PLAIN text generation
               call, not structured_output_model= — transcription doesn't
               need a schema, and this sidesteps the open question in
               docs/sdk-notes.md's 2026-09-19 entry about
               structured_output_model= reliability on GeminiModel
               entirely. Routed through llm_cache.cached_call like every
               model call in this repo (keyed on the image bytes' hash, so
               identical images share a cache entry regardless of prompt
               text staying fixed) — replay mode never touches the network
               even for this backend.

Output is cached per (backend, source-file-hash) under
fixtures/ocr_cache/<backend>/<hash>.json. For the deterministic backends
this is cache-forever (no replay/record distinction, unlike llm_cache.py);
for "vision" it sits on top of llm_cache's own replay/record caching, so a
committed fixtures/ocr_cache/vision/*.json entry short-circuits before
llm_cache is even consulted. The cache is committed so tests and repeat
runs never need to re-run OCR or re-call a model.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Callable

DEFAULT_CACHE_DIR = Path(__file__).parent.parent / "fixtures" / "ocr_cache"

_VISION_PROMPT = (
    "Transcribe every piece of text visible in this document image, exactly as "
    "written, preserving line breaks and field labels. Do not summarize, "
    "translate, or explain anything - output only the transcribed text."
)

_rapidocr_engine = None


def _get_rapidocr_engine():
    global _rapidocr_engine
    if _rapidocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _rapidocr_engine = RapidOCR()
    return _rapidocr_engine


def _run_pdf(path: Path, llm_mode: str | None = None) -> str:
    """A PDF document, not an image. Real users upload certificates as
    PDFs constantly — handing those bytes to an image decoder just raises
    "cannot identify image file". pdfplumber is already a dependency (the
    requirement extractor reads scheme PDFs with it) and needs no model
    call at all for a text-layer PDF."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n\n".join(pages).strip()


def _run_rapidocr(path: Path, llm_mode: str | None = None) -> str:
    engine = _get_rapidocr_engine()
    result, _elapse = engine(str(path))
    if not result:
        return ""
    return "\n".join(line[1] for line in result)


def _run_tesseract(path: Path, llm_mode: str | None = None) -> str:
    import pytesseract
    from PIL import Image

    with Image.open(path) as img:
        return pytesseract.image_to_string(img)


_IMAGE_FORMAT_ALIASES = {"jpg": "jpeg"}


def _run_vision(path: Path, llm_mode: str | None = None) -> str:
    from strands import Agent

    from llm_cache import cached_call
    from model_provider import get_model, get_model_identifier
    from tools.retry import with_retries

    provider = os.environ.get("KAGAZ_MODEL_PROVIDER", "vertex")
    model_name = get_model_identifier(provider)

    image_bytes = path.read_bytes()
    image_format = _IMAGE_FORMAT_ALIASES.get(path.suffix.lstrip(".").lower(), path.suffix.lstrip(".").lower() or "jpeg")

    def call_fn():
        agent = Agent(model=get_model(provider))
        result = agent(
            [
                {
                    "role": "user",
                    "content": [
                        {"text": _VISION_PROMPT},
                        {"image": {"format": image_format, "source": {"bytes": image_bytes}}},
                    ],
                }
            ]
        )
        return {"text": str(result)}

    inputs = {"image_sha256": hashlib.sha256(image_bytes).hexdigest()}
    # Several documents are verified in parallel, so a run can trip the
    # provider's per-minute quota. Back off and retry rather than
    # reporting the user's document as unreadable.
    response = cached_call(
        provider, model_name, _VISION_PROMPT, inputs, lambda: with_retries(call_fn), mode=llm_mode
    )
    return response["text"]


_BACKENDS: dict[str, Callable[..., str]] = {
    "rapidocr": _run_rapidocr,
    "tesseract": _run_tesseract,
    "vision": _run_vision,
    "pdf": _run_pdf,
}


def _default_backend() -> str:
    """vision when the current provider is vertex (Gemini reads images
    directly, so there's no reason to run a separate deterministic OCR
    pass first); rapidocr otherwise, so KAGAZ_MODEL_PROVIDER=ollama still
    runs fully offline with no model-based OCR dependency."""
    if os.environ.get("KAGAZ_MODEL_PROVIDER", "vertex") == "vertex":
        return "vision"
    return "rapidocr"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:24]


def _cache_path(backend: str, file_hash: str, cache_dir: Path) -> Path:
    return cache_dir / backend / f"{file_hash}.json"


def extract_text(
    image_path: Path | str,
    backend: str | None = None,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    llm_mode: str | None = None,
) -> str:
    """Extract text from one document image, cached per (backend, file
    hash) under cache_dir. The real-account flow passes a non-committed
    scratch cache_dir and llm_mode="live" explicitly — never the default
    fixtures/ocr_cache/, and never silently replayed/cached."""
    path = Path(image_path)
    # A PDF is routed by file type, not by KAGAZ_OCR_BACKEND: no image
    # backend can decode one, and its text layer needs no OCR at all.
    if path.suffix.lower() == ".pdf":
        backend = "pdf"
    else:
        backend = backend or os.environ.get("KAGAZ_OCR_BACKEND") or _default_backend()
    if backend not in _BACKENDS:
        raise ValueError(f"Unknown KAGAZ_OCR_BACKEND: {backend!r}")

    file_hash = _file_hash(path)
    cache_path = _cache_path(backend, file_hash, cache_dir)
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))["text"]

    text = _BACKENDS[backend](path, llm_mode=llm_mode)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {"source_file": str(path), "backend": backend, "text": text},
            indent=2,
        ),
        encoding="utf-8",
    )
    return text
