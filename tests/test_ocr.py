from pathlib import Path

import pytest

from tools.ocr import _default_backend, extract_text

MARKSHEET = Path(__file__).parent.parent / "fixtures" / "students" / "priya_nair" / "documents" / "marksheet.jpg"
# Never run through OCR/vision in the real pipeline (photo/signature use
# tools/image_checks.py directly) - guaranteed to have no recorded fixture
# under any backend, unlike MARKSHEET (which does, once vision fixtures
# were recorded for the verifier tests).
UNRECORDED_IMAGE = Path(__file__).parent.parent / "fixtures" / "students" / "priya_nair" / "documents" / "photo.jpg"


def test_ocr_marksheet_contains_name_and_roll_number():
    text = extract_text(MARKSHEET, backend="rapidocr")
    assert "Priya Ramesh Nair" in text
    assert "KL-2026-04471" in text


def test_ocr_result_is_cached(tmp_path):
    text_first = extract_text(MARKSHEET, backend="rapidocr", cache_dir=tmp_path)
    cache_files = list((tmp_path / "rapidocr").glob("*.json"))
    assert len(cache_files) == 1

    text_second = extract_text(MARKSHEET, backend="rapidocr", cache_dir=tmp_path)
    assert text_first == text_second
    # still exactly one cache file - second call was served from cache, not a fresh OCR run
    assert len(list((tmp_path / "rapidocr").glob("*.json"))) == 1


def test_cache_is_keyed_by_backend_not_just_file(tmp_path):
    extract_text(MARKSHEET, backend="rapidocr", cache_dir=tmp_path)
    assert (tmp_path / "rapidocr").exists()
    assert not (tmp_path / "tesseract").exists()


def test_unknown_backend_raises():
    with pytest.raises(ValueError):
        extract_text(MARKSHEET, backend="paddleocr")


def test_backend_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("KAGAZ_OCR_BACKEND", "rapidocr")
    text = extract_text(MARKSHEET, cache_dir=tmp_path)
    assert "Priya Ramesh Nair" in text


# --- default backend resolution: vision when provider is vertex ------------


def test_default_backend_is_vision_when_provider_is_vertex(monkeypatch):
    monkeypatch.setenv("KAGAZ_MODEL_PROVIDER", "vertex")
    monkeypatch.delenv("KAGAZ_OCR_BACKEND", raising=False)
    assert _default_backend() == "vision"


def test_default_backend_is_rapidocr_when_provider_is_ollama(monkeypatch):
    monkeypatch.setenv("KAGAZ_MODEL_PROVIDER", "ollama")
    monkeypatch.delenv("KAGAZ_OCR_BACKEND", raising=False)
    assert _default_backend() == "rapidocr"


def test_explicit_backend_overrides_provider_based_default(monkeypatch, tmp_path):
    # even with provider=vertex (which would default to vision), an
    # explicit KAGAZ_OCR_BACKEND must win
    monkeypatch.setenv("KAGAZ_MODEL_PROVIDER", "vertex")
    monkeypatch.setenv("KAGAZ_OCR_BACKEND", "rapidocr")
    text = extract_text(MARKSHEET, cache_dir=tmp_path)
    assert "Priya Ramesh Nair" in text


# --- vision backend: a real model call, routed through llm_cache -----------


def test_vision_backend_is_a_plain_text_call_not_structured_output():
    # the vision backend must never import structured_output_model= - see
    # tools/ocr.py's docstring for why (sidesteps the open
    # strands-agents/sdk-python#1121 question entirely)
    import tools.ocr

    source = Path(tools.ocr.__file__).read_text(encoding="utf-8")
    vision_fn_source = source.split("def _run_vision")[1].split("\ndef ")[0]
    assert "structured_output_model" not in vision_fn_source


def test_vision_backend_replay_mode_raises_cache_miss_without_network(monkeypatch, tmp_path):
    # No fixture has been recorded for this image under the vision
    # backend, so replay mode must refuse rather than silently call a
    # real model - same guarantee as every other model call in this repo.
    from llm_cache import LLMCacheMiss

    monkeypatch.setenv("KAGAZ_LLM_MODE", "replay")
    monkeypatch.setenv("KAGAZ_MODEL_PROVIDER", "vertex")
    with pytest.raises(LLMCacheMiss):
        extract_text(UNRECORDED_IMAGE, backend="vision", cache_dir=tmp_path)


SCHEME_PDF = Path(__file__).parent.parent / "fixtures" / "schemes" / "scheme_a_postmatric.pdf"


def test_pdf_documents_are_read_by_text_layer_not_an_image_backend(tmp_path):
    # Real users upload certificates as PDFs. Handing those bytes to an
    # image decoder raises "cannot identify image file"; extract_text must
    # route by file type instead, with no model call at all.
    text = extract_text(SCHEME_PDF, cache_dir=tmp_path)
    assert "Post-Matric" in text
    assert (tmp_path / "pdf").is_dir()


def test_pdf_routing_ignores_the_configured_image_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("KAGAZ_OCR_BACKEND", "vision")
    # Would be a cache miss / network call if it actually used "vision".
    text = extract_text(SCHEME_PDF, cache_dir=tmp_path)
    assert text.strip()
