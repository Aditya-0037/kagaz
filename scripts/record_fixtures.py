"""Record LLM cache fixtures: requirement extraction (phase 4) and
document verification (phase 5c).

Run with: .venv/Scripts/python.exe scripts/record_fixtures.py
Or against the offline dev fallback: KAGAZ_MODEL_PROVIDER=ollama .venv/Scripts/python.exe scripts/record_fixtures.py

Runs both scheme PDFs through the real extractor, and all five
certificate-style verifiers against all three students' documents, against
the default provider (Vertex AI / Gemini — see docs/vertex-setup.md) with
KAGAZ_LLM_MODE=record, writing responses to fixtures/llm_cache/. Run this
once, inspect the printed output below, and hand-correct any
fixtures/llm_cache/*.json entries where the model got something wrong —
from here on the fixtures are the test contract, not the model's live
opinion. Requires GOOGLE_CLOUD_PROJECT set and Application Default
Credentials configured (`gcloud auth application-default login`), or set
KAGAZ_MODEL_PROVIDER=ollama to record against a local Ollama model instead
(requires `ollama serve` running locally with llama3.1:8b pulled).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # repo root, for `agents.*`/`tools.*` imports

os.environ["KAGAZ_LLM_MODE"] = "record"
os.environ.setdefault("KAGAZ_MODEL_PROVIDER", "vertex")

from agents.requirement_extractor import extract_requirement_from_pdf  # noqa: E402
from agents.verifiers import VERIFIERS  # noqa: E402
from tools.ocr import extract_text  # noqa: E402

SCHEMES_DIR = Path(__file__).parent.parent / "fixtures" / "schemes"
STUDENTS_DIR = Path(__file__).parent.parent / "fixtures" / "students"

SCHEMES = [
    ("scheme_a_postmatric.pdf", "scheme_a_postmatric", "Post-Matric Scholarship for Minority Communities 2026-27"),
    ("scheme_b_merit.pdf", "scheme_b_merit", "State Merit Scholarship 2026"),
]

STUDENT_IDS = ["priya_nair", "aditya_sharma", "mohammed_irfan"]


def record_requirements() -> None:
    for filename, scheme_id, scheme_name in SCHEMES:
        print(f"\n{'=' * 70}\nRecording requirement: {scheme_id} ({filename})\n{'=' * 70}")
        requirement = extract_requirement_from_pdf(SCHEMES_DIR / filename, scheme_id, scheme_name)
        print(requirement.model_dump_json(indent=2))


def record_verifiers() -> None:
    for student_id in STUDENT_IDS:
        docs_dir = STUDENTS_DIR / student_id / "documents"
        for doc_type, verify in VERIFIERS.items():
            source_path = docs_dir / f"{doc_type}.jpg"
            print(f"\n{'=' * 70}\nRecording verifier: {student_id} / {doc_type}\n{'=' * 70}")
            ocr_text = extract_text(source_path)
            document, usage = verify(ocr_text, source_path, student_id=student_id)
            print(document.model_dump_json(indent=2))
            print("usage:", usage)


def main() -> None:
    record_requirements()
    record_verifiers()


if __name__ == "__main__":
    main()
