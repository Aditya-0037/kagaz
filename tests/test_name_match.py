import pytest

from tools.name_match import compare_names, levenshtein, normalize_name

# --- identical -------------------------------------------------------------


def test_identical_exact():
    assert compare_names("Aditya Kumar Sharma", "Aditya Kumar Sharma").verdict == "match"


def test_identical_case_insensitive():
    assert compare_names("aditya kumar sharma", "ADITYA KUMAR SHARMA").verdict == "match"


def test_identical_after_honorific_strip():
    assert compare_names("Mr. Aditya Kumar Sharma", "Aditya Kumar Sharma").verdict == "match"


def test_identical_after_punctuation_and_case_normalisation():
    assert compare_names("aditya KUMAR, sharma", "Aditya Kumar Sharma").verdict == "match"


# --- strict subset -----------------------------------------------------------


def test_subset_omitted_surname_direction_a_smaller():
    result = compare_names("Aditya Kumar", "Aditya Kumar Sharma")
    assert result.verdict == "likely_fine"


def test_subset_omitted_surname_direction_b_smaller():
    result = compare_names("Aditya Kumar Sharma", "Aditya Kumar")
    assert result.verdict == "likely_fine"


def test_subset_bank_passbook_style_middle_name_dropped():
    result = compare_names("Aditya Kumar Sharma", "Aditya Sharma")
    assert result.verdict == "likely_fine"


def test_subset_with_honorific_on_longer_name():
    result = compare_names("Dr. Aditya Kumar Sharma", "Aditya Kumar")
    assert result.verdict == "likely_fine"


# --- initial expansion -------------------------------------------------------


def test_initial_expansion_full_form():
    result = compare_names("A. K. Sharma", "Aditya Kumar Sharma")
    assert result.verdict == "likely_fine"


def test_initial_expansion_reversed_direction():
    result = compare_names("Aditya Kumar Sharma", "A. K. Sharma")
    assert result.verdict == "likely_fine"


def test_initial_expansion_single_initial_two_tokens():
    result = compare_names("A. Sharma", "Aditya Sharma")
    assert result.verdict == "likely_fine"


def test_initial_expansion_glued_initials_no_space():
    # Real documents/OCR often drop the space between initials
    # ("A.K." instead of "A. K.") — must compare the same as spaced.
    result = compare_names("A.K. Sharma", "Aditya Kumar Sharma")
    assert result.verdict == "likely_fine"


def test_glued_and_spaced_initials_are_equivalent():
    assert normalize_name("A.K. Sharma") == normalize_name("A. K. Sharma")


# --- order variance -----------------------------------------------------------


def test_order_variance_surname_first():
    result = compare_names("Sharma Aditya Kumar", "Aditya Kumar Sharma")
    assert result.verdict == "likely_fine"


def test_order_variance_two_tokens():
    result = compare_names("Nair Priya", "Priya Nair")
    assert result.verdict == "likely_fine"


# --- transliteration variants (edit distance 1-2 on a single token) ----------


def test_transliteration_aditya_aaditya():
    result = compare_names("Aditya Sharma", "Aaditya Sharma")
    assert result.verdict == "worth_knowing"


def test_transliteration_kumar_kumaar():
    result = compare_names("Rakesh Kumar", "Rakesh Kumaar")
    assert result.verdict == "worth_knowing"


def test_transliteration_rakesh_rakhesh():
    result = compare_names("Rakesh Yadav", "Rakhesh Yadav")
    assert result.verdict == "worth_knowing"


def test_transliteration_edit_distance_exactly_2_is_worth_knowing():
    # "kumhaar" is exactly 2 insertions away from "kumar"
    assert levenshtein("kumar", "kumhaar") == 2
    result = compare_names("Aditya Kumar", "Aditya Kumhaar")
    assert result.verdict == "worth_knowing"


def test_edit_distance_3_is_blocker_not_transliteration():
    # "kumhaars" is exactly 3 insertions away from "kumar" - past the window
    assert levenshtein("kumar", "kumhaars") == 3
    result = compare_names("Aditya Kumar", "Aditya Kumhaars")
    assert result.verdict == "blocker"


# --- blockers ------------------------------------------------------------------


def test_blocker_surname_swap_same_position():
    result = compare_names("Aditya Kumar Sharma", "Aditya Kumar Verma")
    assert result.verdict == "blocker"


def test_blocker_completely_disjoint():
    result = compare_names("Priya Ramesh Nair", "Fatima Ayesha Khan")
    assert result.verdict == "blocker"


def test_blocker_partial_overlap_beyond_translit_window():
    result = compare_names("Aditya Sharma", "Aditya Gupta")
    assert result.verdict == "blocker"


def test_blocker_different_length_no_subset_relationship():
    result = compare_names("Aditya Kumar Sharma", "Rohan Verma")
    assert result.verdict == "blocker"


# --- normalisation helper -------------------------------------------------------


def test_normalize_strips_honorifics_and_punctuation():
    assert normalize_name("Dr. Aditya Kumar Sharma,") == ["aditya", "kumar", "sharma"]


def test_normalize_casefolds():
    assert normalize_name("PRIYA NAIR") == ["priya", "nair"]


@pytest.mark.parametrize(
    "a,b,expected_distance",
    [
        ("sharma", "sharma", 0),
        ("kumar", "kumaar", 1),
        ("rakesh", "rakhesh", 1),
        ("aditya", "aaditya", 1),
    ],
)
def test_levenshtein_known_distances(a, b, expected_distance):
    assert levenshtein(a, b) == expected_distance
