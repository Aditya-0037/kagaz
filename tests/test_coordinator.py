"""Coordinator tests.

test_regression_* is the guard against the deadline-propagation bug: the
extractor always sets must_be_valid_on=None (spec — it doesn't invent a
per-document validity policy), and cross_checker skips any document whose
must_be_valid_on is None. Unfixed, that means an unmodified extractor ->
cross-checker pipeline could never produce an expiry finding, silently
letting mohammed_irfan's expired income certificate through. The earlier
cross-checker test only passed because it hand-built a RequiredDoc with
must_be_valid_on already set — this test instead uses a real Requirement
straight out of the extractor.
"""

from pathlib import Path

import pytest

from agents.coordinator import apply_deadline, run_audit
from agents.cross_checker import audit_student
from agents.requirement_extractor import extract_requirement_from_pdf
from contracts import RequiredDoc, Requirement
from fixtures_loader import student_documents

SCHEMES_DIR = Path(__file__).parent.parent / "fixtures" / "schemes"
SCHEME_A_PDF = SCHEMES_DIR / "scheme_a_postmatric.pdf"
SCHEME_A_NAME = "Post-Matric Scholarship 2026-27"


@pytest.fixture(autouse=True)
def _replay_mode(monkeypatch):
    monkeypatch.setenv("KAGAZ_LLM_MODE", "replay")
    monkeypatch.setenv("KAGAZ_MODEL_PROVIDER", "vertex")


@pytest.fixture(scope="module")
def scheme_a_requirement():
    # Module-scoped fixtures are set up before function-scoped ones (like
    # the autouse _replay_mode above), regardless of declaration order —
    # so this needs its own env, not a reliance on _replay_mode having
    # already run. (This only stayed invisible before because the old
    # default provider happened to also be "ollama".)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KAGAZ_LLM_MODE", "replay")
        mp.setenv("KAGAZ_MODEL_PROVIDER", "vertex")
        return extract_requirement_from_pdf(
            SCHEMES_DIR / "scheme_a_postmatric.pdf", "scheme_a_postmatric", "Post-Matric Scholarship 2026-27"
        )


def test_apply_deadline_sets_must_be_valid_on_for_expiring_docs(scheme_a_requirement):
    updated = apply_deadline(scheme_a_requirement)
    by_type = {rd.doc_type: rd for rd in updated.required_documents}

    for doc_type in ("income_certificate", "caste_certificate", "domicile_certificate"):
        assert by_type[doc_type].must_be_valid_on == scheme_a_requirement.deadline

    for doc_type in ("marksheet", "bank_passbook", "photo", "signature"):
        assert by_type[doc_type].must_be_valid_on is None


def test_apply_deadline_does_not_mutate_input(scheme_a_requirement):
    apply_deadline(scheme_a_requirement)
    assert all(rd.must_be_valid_on is None for rd in scheme_a_requirement.required_documents)


def test_apply_deadline_is_noop_without_a_deadline():
    req = Requirement(
        scheme_id="x",
        scheme_name="X",
        deadline=None,
        required_documents=[RequiredDoc(doc_type="income_certificate")],
        source="manual",
        confidence=1.0,
    )
    updated = apply_deadline(req)
    assert updated.required_documents[0].must_be_valid_on is None


def test_regression_extractor_output_through_apply_deadline_produces_expiry_blocker(scheme_a_requirement):
    requirement = apply_deadline(scheme_a_requirement)
    documents = student_documents("mohammed_irfan")

    findings = audit_student(documents, requirement.required_documents)

    expiry_findings = [f for f in findings if f.category == "expired"]
    assert len(expiry_findings) == 1
    assert expiry_findings[0].severity == "blocker"
    assert expiry_findings[0].needs_human is True
    assert "income_certificate" in expiry_findings[0].evidence[0]


# --- run_audit: end-to-end, from a scheme PDF through to findings -----------
#
# Phase 5d acceptance: all three students run end to end from scheme A's
# PDF, replay mode, network off. priya_nair -> 0 findings (clean case).
# aditya_sharma -> 2 likely_fine (name variance). mohammed_irfan -> 2
# blockers, including the expiry one — the bug fixed in 5a, now exercised
# through the real coordinator rather than a hand-built RequiredDoc.


def test_priya_nair_end_to_end_zero_findings():
    result = run_audit("priya_nair", "scheme_a_postmatric", SCHEME_A_NAME, SCHEME_A_PDF)
    assert result.student_id == "priya_nair"
    assert result.scheme_id == "scheme_a_postmatric"
    assert result.findings == []
    assert len(result.extracted_documents) == 7  # all 7 of scheme A's required documents
    assert result.duration_seconds >= 0


def test_aditya_sharma_end_to_end_two_likely_fine():
    result = run_audit("aditya_sharma", "scheme_a_postmatric", SCHEME_A_NAME, SCHEME_A_PDF)
    assert len(result.findings) == 2
    assert all(f.severity == "likely_fine" for f in result.findings)
    assert all(f.category == "name_mismatch" for f in result.findings)
    assert all(f.needs_human is False for f in result.findings)


def test_mohammed_irfan_end_to_end_two_blockers():
    result = run_audit("mohammed_irfan", "scheme_a_postmatric", SCHEME_A_NAME, SCHEME_A_PDF)
    assert len(result.findings) == 2
    assert all(f.severity == "blocker" for f in result.findings)
    assert all(f.needs_human is True for f in result.findings)
    assert {f.category for f in result.findings} == {"dob_mismatch", "expired"}


def test_extracted_documents_are_sorted_deterministically_despite_parallel_execution():
    result = run_audit("priya_nair", "scheme_a_postmatric", SCHEME_A_NAME, SCHEME_A_PDF)
    doc_types = [d.doc_type for d in result.extracted_documents]
    assert doc_types == sorted(doc_types)


def test_audit_result_carries_token_usage_and_duration():
    result = run_audit("priya_nair", "scheme_a_postmatric", SCHEME_A_NAME, SCHEME_A_PDF)
    assert result.token_usage.get("totalTokens", 0) > 0
    assert result.duration_seconds >= 0


def test_photo_and_signature_do_not_produce_findings_from_format_issues():
    # priya_nair's photo is deliberately oversized/wrong-dimension (spec
    # section 8: the formatter, not the audit, is what fixes this) — it
    # must not show up as a Finding requiring human review.
    result = run_audit("priya_nair", "scheme_a_postmatric", SCHEME_A_NAME, SCHEME_A_PDF)
    photo_doc = next(d for d in result.extracted_documents if d.doc_type == "photo")
    assert photo_doc.extraction_confidence < 1.0  # the check does notice
    assert result.findings == []  # but it's not escalated as a Finding


def test_one_unreadable_document_becomes_a_finding_not_a_crashed_run(tmp_path):
    # A corrupt scan / wrong file type for one document must not take the
    # whole audit down: it becomes a blocker finding against that document
    # and everything else still gets checked.
    from agents.coordinator import run_audit_for_documents
    from contracts import Requirement, RequiredDoc

    junk = tmp_path / "not_really_an_image.jpg"
    junk.write_bytes(b"this is not an image at all")

    requirement = Requirement(
        scheme_id="unreadable_test",
        scheme_name="Unreadable Test",
        required_documents=[RequiredDoc(doc_type="income_certificate")],
        required_fields=[],
        source="text",
        confidence=1.0,
    )

    result = run_audit_for_documents("someone", "unreadable_test", requirement, {"income_certificate": junk})

    assert [f.category for f in result.findings] == ["format"]
    assert "could not read" in result.findings[0].message.lower()
    assert result.findings[0].severity == "blocker"


def test_real_runs_never_write_ocr_text_into_the_committed_fixtures_dir(tmp_path, monkeypatch):
    # Regression: a real user's document OCR text once landed in
    # fixtures/ocr_cache/, which is git-tracked and pushed publicly. Real
    # runs must cache OCR somewhere gitignored instead.
    import agents.coordinator as coordinator
    from tools.ocr import DEFAULT_CACHE_DIR

    seen: dict[str, object] = {}

    def fake_extract_text(path, backend=None, *, cache_dir=None, llm_mode=None):
        seen["cache_dir"] = cache_dir
        seen["llm_mode"] = llm_mode
        return "OCR TEXT"

    def fake_verify(ocr_text, source_path, *, student_id, llm_mode=None):
        from contracts import ExtractedDocument

        return ExtractedDocument(
            doc_type="income_certificate", source_path=source_path, extraction_confidence=1.0
        ), {}

    monkeypatch.setattr(coordinator, "extract_text", fake_extract_text)
    monkeypatch.setitem(coordinator.VERIFIERS, "income_certificate", fake_verify)

    from contracts import Requirement, RequiredDoc

    doc = tmp_path / "income_certificate.jpg"
    doc.write_bytes(b"x")
    requirement = Requirement(
        scheme_id="s",
        scheme_name="S",
        required_documents=[RequiredDoc(doc_type="income_certificate")],
        required_fields=[],
        source="text",
        confidence=1.0,
    )

    coordinator.run_real_audit_with_escalation(
        "user1", "run1", requirement, {"income_certificate": doc}, lambda finding: ("accept", None)
    )

    assert seen["llm_mode"] == "live"
    assert seen["cache_dir"] == coordinator.REAL_OCR_CACHE_DIR
    assert DEFAULT_CACHE_DIR not in (seen["cache_dir"], seen["cache_dir"].parent)
    assert "fixtures" not in str(seen["cache_dir"])
