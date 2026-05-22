"""Branch-coverage unit tests for _parse_log_message and _fuzzy_match_clinic."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import _parse_log_message, _fuzzy_match_clinic

# Shorthand: None means no date in text, caller defaults to today
D = None  # no date (default today)


# =============================================================================
# _parse_log_message — no-date variants (all existing tests)
# =============================================================================

def test_empty_or_whitespace():
    assert _parse_log_message("") is None
    assert _parse_log_message("   ") is None
    assert _parse_log_message("\t\n") is None


def test_unrecognized_token():
    assert _parse_log_message("abc") is None
    assert _parse_log_message("xyz foo") is None


def test_all_zeros():
    assert _parse_log_message("0") is None
    assert _parse_log_message("0 0") is None
    assert _parse_log_message("0 0 0") is None
    assert _parse_log_message("0h") is None
    assert _parse_log_message("0h 0 0") is None


def test_h_suffix():
    assert _parse_log_message("4h") == (D, 4.0, 0.0, 0.0)
    assert _parse_log_message("0.5h") == (D, 0.5, 0.0, 0.0)
    assert _parse_log_message("8.25h") == (D, 8.25, 0.0, 0.0)
    assert _parse_log_message("4H") == (D, 4.0, 0.0, 0.0)


def test_i_prefix():
    assert _parse_log_message("i5000") == (D, 0.0, 5000.0, 0.0)
    assert _parse_log_message("i1234.56") == (D, 0.0, 1234.56, 0.0)


def test_i_suffix():
    assert _parse_log_message("5000i") == (D, 0.0, 5000.0, 0.0)
    assert _parse_log_message("500.50i") == (D, 0.0, 500.50, 0.0)


def test_i_uppercase():
    assert _parse_log_message("I5000") == (D, 0.0, 5000.0, 0.0)
    assert _parse_log_message("5000I") == (D, 0.0, 5000.0, 0.0)


def test_e_prefix():
    assert _parse_log_message("e500") == (D, 0.0, 0.0, 500.0)
    assert _parse_log_message("e50.25") == (D, 0.0, 0.0, 50.25)


def test_e_suffix():
    assert _parse_log_message("500e") == (D, 0.0, 0.0, 500.0)
    assert _parse_log_message("50.50e") == (D, 0.0, 0.0, 50.50)


def test_e_uppercase():
    assert _parse_log_message("E500") == (D, 0.0, 0.0, 500.0)
    assert _parse_log_message("500E") == (D, 0.0, 0.0, 500.0)


def test_expense_only():
    assert _parse_log_message("e500") == (D, 0.0, 0.0, 500.0)
    assert _parse_log_message("500e") == (D, 0.0, 0.0, 500.0)


def test_expense_only_with_hours():
    assert _parse_log_message("0h e500") == (D, 0.0, 0.0, 500.0)
    assert _parse_log_message("0h 500e") == (D, 0.0, 0.0, 500.0)


def test_all_explicit():
    assert _parse_log_message("4h i5000 e100") == (D, 4.0, 5000.0, 100.0)
    assert _parse_log_message("4h 5000i 100e") == (D, 4.0, 5000.0, 100.0)
    assert _parse_log_message("4h i5000 100e") == (D, 4.0, 5000.0, 100.0)
    assert _parse_log_message("4h 5000i e100") == (D, 4.0, 5000.0, 100.0)
    assert _parse_log_message("4H I5000 E100") == (D, 4.0, 5000.0, 100.0)


def test_explicit_income_and_expense():
    assert _parse_log_message("i5000 e100") == (D, 0.0, 5000.0, 100.0)
    assert _parse_log_message("5000i 100e") == (D, 0.0, 5000.0, 100.0)


def test_positional_one():
    assert _parse_log_message("4") == (D, 4.0, 0.0, 0.0)


def test_positional_two():
    assert _parse_log_message("4 5000") == (D, 4.0, 5000.0, 0.0)


def test_positional_three():
    assert _parse_log_message("4 5000 100") == (D, 4.0, 5000.0, 100.0)


def test_positional_overflow():
    assert _parse_log_message("4 5000 100 200") == (D, 4.0, 5000.0, 100.0)
    assert _parse_log_message("4 5000 100 200 300") == (D, 4.0, 5000.0, 100.0)


def test_explicit_hours_plus_positional():
    assert _parse_log_message("4h 5000") == (D, 4.0, 5000.0, 0.0)
    assert _parse_log_message("4h 5000 100") == (D, 4.0, 5000.0, 100.0)


def test_explicit_income_plus_positional():
    assert _parse_log_message("i4000 4") == (D, 4.0, 4000.0, 0.0)
    assert _parse_log_message("i4000 4 100") == (D, 4.0, 4000.0, 100.0)
    assert _parse_log_message("5000i 4 100") == (D, 4.0, 5000.0, 100.0)


def test_explicit_expense_plus_positional():
    assert _parse_log_message("e100 4") == (D, 4.0, 0.0, 100.0)
    assert _parse_log_message("e100 4 5000") == (D, 4.0, 5000.0, 100.0)
    assert _parse_log_message("4 5000 e100") == (D, 4.0, 5000.0, 100.0)


def test_mixed_hours_income_explicit_expense_positional():
    assert _parse_log_message("4h i5000 100") == (D, 4.0, 5000.0, 100.0)


def test_mixed_income_expense_explicit_hours_positional():
    assert _parse_log_message("4 i5000 e100") == (D, 4.0, 5000.0, 100.0)


def test_income_explicit_hours_expense_positional():
    assert _parse_log_message("5000i 4 100") == (D, 4.0, 5000.0, 100.0)


def test_token_order():
    assert _parse_log_message("i5000 4h e100") == (D, 4.0, 5000.0, 100.0)
    assert _parse_log_message("e100 4h i5000") == (D, 4.0, 5000.0, 100.0)
    assert _parse_log_message("4h e100 i5000") == (D, 4.0, 5000.0, 100.0)


def test_unrecognized_mid_stream():
    assert _parse_log_message("4 abc 5000") is None
    assert _parse_log_message("4h xyz") is None


# =============================================================================
# _parse_log_message — date-specification tests (NEW)
# =============================================================================

def test_date_basic():
    """d/m as last token → extracted as date string."""
    assert _parse_log_message("4 5000 22/5") == ("05-22", 4.0, 5000.0, 0.0)
    assert _parse_log_message("4 5000 100 22/5") == ("05-22", 4.0, 5000.0, 100.0)


def test_date_explicit_markers():
    """Date works with explicit value markers."""
    assert _parse_log_message("4h i5000 e100 22/5") == ("05-22", 4.0, 5000.0, 100.0)
    assert _parse_log_message("4h 5000i 100e 1/12") == ("12-01", 4.0, 5000.0, 100.0)
    assert _parse_log_message("i5000 100e 15/6") == ("06-15", 0.0, 5000.0, 100.0)
    assert _parse_log_message("e500 7/3") == ("03-07", 0.0, 0.0, 500.0)


def test_date_single_value():
    """Date with single value."""
    assert _parse_log_message("4h 22/5") == ("05-22", 4.0, 0.0, 0.0)
    assert _parse_log_message("5000i 1/1") == ("01-01", 0.0, 5000.0, 0.0)
    assert _parse_log_message("500e 31/12") == ("12-31", 0.0, 0.0, 500.0)


def test_date_edge_days():
    """Edge day values."""
    assert _parse_log_message("4 5000 1/5") == ("05-01", 4.0, 5000.0, 0.0)
    assert _parse_log_message("4 5000 31/5") == ("05-31", 4.0, 5000.0, 0.0)


def test_date_edge_months():
    """Edge month values."""
    assert _parse_log_message("4 5000 22/1") == ("01-22", 4.0, 5000.0, 0.0)
    assert _parse_log_message("4 5000 22/12") == ("12-22", 4.0, 5000.0, 0.0)


def test_date_single_digit():
    """Single digit day and month."""
    assert _parse_log_message("4 5000 5/5") == ("05-05", 4.0, 5000.0, 0.0)
    assert _parse_log_message("4 5000 9/3") == ("03-09", 4.0, 5000.0, 0.0)


def test_date_only_rejected():
    """Date only with no values → None (no work to log)."""
    assert _parse_log_message("22/5") is None
    assert _parse_log_message("1/12") is None


def test_date_all_zeros_with_date_rejected():
    """All zeros + date → None (no meaningful work)."""
    assert _parse_log_message("0 0 22/5") is None
    assert _parse_log_message("0h 22/5") is None


def test_date_invalid_range_still_parsed():
    """Parser extracts d/m with basic range check (1-31 day, 1-12 month).
    Impossible dates (e.g. Feb 30) are caught by webhook handler via strptime."""
    # Valid range, accepted by parser
    assert _parse_log_message("4 5000 30/2") == ("02-30", 4.0, 5000.0, 0.0)
    # Out of range day → token treated as unrecognized → None
    assert _parse_log_message("4 5000 32/5") is None
    assert _parse_log_message("4 5000 0/5") is None
    # Out of range month → token treated as unrecognized → None
    assert _parse_log_message("4 5000 22/13") is None
    assert _parse_log_message("4 5000 22/0") is None


def test_date_not_last():
    """d/m NOT at end → parsed as positional numbers, d=h, m=income."""
    # "22/5" in middle: "22/5" doesn't match any explicit marker,
    # and isn't a pure number → unrecognized → None
    assert _parse_log_message("22/5 4 5000") is None


def test_date_mixed_with_explicit_order():
    """Date extraction works regardless of explicit token positions."""
    assert _parse_log_message("i5000 4h 100e 22/5") == ("05-22", 4.0, 5000.0, 100.0)
    assert _parse_log_message("e100 i5000 4h 22/5") == ("05-22", 4.0, 5000.0, 100.0)


def test_date_positional_overflow_with_date():
    """Extra positional values before date → first 3 used, rest ignored."""
    assert _parse_log_message("4 5000 100 200 22/5") == ("05-22", 4.0, 5000.0, 100.0)


# =============================================================================
# _fuzzy_match_clinic
# =============================================================================

CLINICS = [
    {"name": "Vela Yim", "id": 1},
    {"name": "Smile Dental", "id": 2},
    {"name": "Bangkok Smile", "id": 3},
    {"name": "The Dental Loft", "id": 4},
]


def test_fuzzy_empty_input():
    assert _fuzzy_match_clinic("", CLINICS) is None
    assert _fuzzy_match_clinic("   ", CLINICS) is None
    assert _fuzzy_match_clinic("\t", CLINICS) is None


def test_fuzzy_exact_match():
    assert _fuzzy_match_clinic("Vela Yim", CLINICS) == CLINICS[0]
    assert _fuzzy_match_clinic("vela yim", CLINICS) == CLINICS[0]
    assert _fuzzy_match_clinic("VELA YIM", CLINICS) == CLINICS[0]
    assert _fuzzy_match_clinic("Velayim", CLINICS) == CLINICS[0]
    assert _fuzzy_match_clinic("velayim", CLINICS) == CLINICS[0]
    assert _fuzzy_match_clinic("Smile Dental", CLINICS) == CLINICS[1]
    assert _fuzzy_match_clinic("smiledental", CLINICS) == CLINICS[1]


def test_fuzzy_substring_match():
    assert _fuzzy_match_clinic("vela", CLINICS) == CLINICS[0]
    assert _fuzzy_match_clinic("yim", CLINICS) == CLINICS[0]
    assert _fuzzy_match_clinic("smile", CLINICS) == CLINICS[1]
    assert _fuzzy_match_clinic("dental", CLINICS) == CLINICS[1]


def test_fuzzy_levenshtein_match():
    assert _fuzzy_match_clinic("vela yum", CLINICS) == CLINICS[0]
    assert _fuzzy_match_clinic("smil dental", CLINICS) == CLINICS[1]
    assert _fuzzy_match_clinic("Bangkok Smile", CLINICS) == CLINICS[2]


def test_fuzzy_no_match():
    assert _fuzzy_match_clinic("zzzzzz", CLINICS) is None
    assert _fuzzy_match_clinic("tooth fairy", CLINICS) is None
    assert _fuzzy_match_clinic("abcdef", CLINICS) is None


def test_fuzzy_single_clinic():
    single = [{"name": "Only Clinic", "id": 99}]
    assert _fuzzy_match_clinic("onlyclinic", single) == single[0]
    assert _fuzzy_match_clinic("only clinic", single) == single[0]
    assert _fuzzy_match_clinic("nope", single) is None


def test_fuzzy_empty_clinic_list():
    assert _fuzzy_match_clinic("anything", []) is None


# =============================================================================
# run
# =============================================================================

if __name__ == "__main__":
    import pytest
    args = ["-v", __file__]
    try:
        import pytest_cov
        args.insert(0, "--cov=app")
        args.insert(1, "--cov-branch")
    except ImportError:
        pass
    sys.exit(pytest.main(args))
