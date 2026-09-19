import pytest

from tools.doc_types import normalize_doc_type


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Income Certificate", "income_certificate"),
        ("income certificate", "income_certificate"),
        ("Income Certificate issued by Tehsildar", "income_certificate"),
        ("Caste Certificate", "caste_certificate"),
        ("Domicile Certificate", "domicile_certificate"),
        ("Residence Certificate", "domicile_certificate"),
        ("Marksheet", "marksheet"),
        ("Mark Sheet", "marksheet"),
        ("Most recent Marksheet", "marksheet"),
        ("Bank Passbook", "bank_passbook"),
        ("Bank Passbook (first page)", "bank_passbook"),
        ("Photograph", "photo"),
        ("Recent Photograph", "photo"),
        ("Passport-size Photograph", "photo"),
        ("Signature", "signature"),
        ("Specimen Signature", "signature"),
    ],
)
def test_normalize_known_labels(label, expected):
    assert normalize_doc_type(label) == expected


def test_normalize_unknown_label_falls_back_to_slug():
    assert normalize_doc_type("NCC Certificate") == "ncc_certificate"


def test_normalize_is_idempotent_on_canonical_forms():
    assert normalize_doc_type("income_certificate") == "income_certificate"
