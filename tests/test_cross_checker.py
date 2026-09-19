"""End-to-end cross-checker behaviour against the three synthetic students.

Phase 2 acceptance: all three students produce exactly the findings the
spec predicts, with zero LLM calls (nothing here imports an agent runtime
or touches llm_cache).
"""

from agents.cross_checker import audit_student
from contracts import RequiredDoc
from fixtures_loader import SCHEME_DEADLINE, student_documents

TODAY = None  # let check_validity default to date.today(); severity is
# stable regardless of when the suite runs (see test_dates.py)

INCOME_CERT_REQUIREMENT = [
    RequiredDoc(doc_type="income_certificate", must_be_valid_on=SCHEME_DEADLINE)
]


def test_priya_nair_clean_case_has_no_findings():
    documents = student_documents("priya_nair")
    findings = audit_student(documents, INCOME_CERT_REQUIREMENT)
    assert findings == []


def test_aditya_sharma_name_variance_is_all_likely_fine():
    documents = student_documents("aditya_sharma")
    findings = audit_student(documents, INCOME_CERT_REQUIREMENT)

    assert len(findings) == 2
    assert all(f.category == "name_mismatch" for f in findings)
    assert all(f.severity == "likely_fine" for f in findings)
    assert all(f.needs_human is False for f in findings)

    doc_types_mentioned = {ev.split(":")[0] for f in findings for ev in f.evidence}
    assert doc_types_mentioned == {"marksheet", "bank_passbook", "domicile_certificate"}


def test_mohammed_irfan_produces_exactly_two_blockers():
    documents = student_documents("mohammed_irfan")
    findings = audit_student(documents, INCOME_CERT_REQUIREMENT)

    assert len(findings) == 2
    assert all(f.severity == "blocker" for f in findings)
    assert all(f.needs_human is True for f in findings)

    categories = {f.category for f in findings}
    assert categories == {"dob_mismatch", "expired"}

    dob_finding = next(f for f in findings if f.category == "dob_mismatch")
    assert any("marksheet" in ev for ev in dob_finding.evidence)
    assert any("domicile_certificate" in ev for ev in dob_finding.evidence)

    expiry_finding = next(f for f in findings if f.category == "expired")
    assert "11" in expiry_finding.message


def test_no_findings_without_a_required_documents_list_still_checks_names_and_dob():
    # validity checks need a Requirement; name/DOB checks don't.
    documents = student_documents("mohammed_irfan")
    findings = audit_student(documents)
    assert len(findings) == 1
    assert findings[0].category == "dob_mismatch"
