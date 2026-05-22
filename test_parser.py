"""Branch-coverage unit tests for _parse_log_message and _fuzzy_match_clinic."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import _parse_log_message, _fuzzy_match_clinic


# =============================================================================
# _parse_log_message
# =============================================================================

def test_empty_or_whitespace():
    """Empty/whitespace input → None."""
    assert _parse_log_message("") is None
    assert _parse_log_message("   ") is None
    assert _parse_log_message("\t\n") is None


def test_unrecognized_token():
    """Single unrecognized token → None."""
    assert _parse_log_message("abc") is None
    assert _parse_log_message("xyz foo") is None


def test_all_zeros():
    """All values resolve to zero → None."""
    assert _parse_log_message("0") is None
    assert _parse_log_message("0 0") is None
    assert _parse_log_message("0 0 0") is None
    assert _parse_log_message("0h") is None          # explicit 0h with no income/expense
    assert _parse_log_message("0h 0 0") is None      # explicit zero but all zero


# --- h suffix (hours explicit) ---

def test_h_suffix():
    """Hours with h suffix."""
    assert _parse_log_message("4h") == (4.0, 0.0, 0.0)
    assert _parse_log_message("0.5h") == (0.5, 0.0, 0.0)
    assert _parse_log_message("8.25h") == (8.25, 0.0, 0.0)
    # uppercase
    assert _parse_log_message("4H") == (4.0, 0.0, 0.0)


# --- i prefix / suffix (income explicit) ---

def test_i_prefix():
    """Income with i prefix."""
    assert _parse_log_message("i5000") == (0.0, 5000.0, 0.0)
    assert _parse_log_message("i1234.56") == (0.0, 1234.56, 0.0)


def test_i_suffix():
    """Income with i suffix."""
    assert _parse_log_message("5000i") == (0.0, 5000.0, 0.0)
    assert _parse_log_message("500.50i") == (0.0, 500.50, 0.0)


def test_i_uppercase():
    """Income with uppercase I."""
    assert _parse_log_message("I5000") == (0.0, 5000.0, 0.0)
    assert _parse_log_message("5000I") == (0.0, 5000.0, 0.0)


# --- e prefix / suffix (expense explicit) ---

def test_e_prefix():
    """Expense with e prefix."""
    assert _parse_log_message("e500") == (0.0, 0.0, 500.0)
    assert _parse_log_message("e50.25") == (0.0, 0.0, 50.25)


def test_e_suffix():
    """Expense with e suffix."""
    assert _parse_log_message("500e") == (0.0, 0.0, 500.0)
    assert _parse_log_message("50.50e") == (0.0, 0.0, 50.50)


def test_e_uppercase():
    """Expense with uppercase E."""
    assert _parse_log_message("E500") == (0.0, 0.0, 500.0)
    assert _parse_log_message("500E") == (0.0, 0.0, 500.0)


# --- expense-only entries (zero hours allowed, migration 007) ---

def test_expense_only():
    """Expense-only log entry."""
    assert _parse_log_message("e500") == (0.0, 0.0, 500.0)
    assert _parse_log_message("500e") == (0.0, 0.0, 500.0)


def test_expense_only_with_hours():
    """Expense + hours with zero-hour allowed."""
    assert _parse_log_message("0h e500") == (0.0, 0.0, 500.0)
    assert _parse_log_message("0h 500e") == (0.0, 0.0, 500.0)


# --- Mixed explicit markers ---

def test_all_explicit():
    """All three values with explicit markers."""
    assert _parse_log_message("4h i5000 e100") == (4.0, 5000.0, 100.0)
    # suffix variants
    assert _parse_log_message("4h 5000i 100e") == (4.0, 5000.0, 100.0)
    # mixed prefix/suffix
    assert _parse_log_message("4h i5000 100e") == (4.0, 5000.0, 100.0)
    assert _parse_log_message("4h 5000i e100") == (4.0, 5000.0, 100.0)
    # mixed case
    assert _parse_log_message("4H I5000 E100") == (4.0, 5000.0, 100.0)


def test_explicit_income_and_expense():
    """Income and expense only (no hours)."""
    assert _parse_log_message("i5000 e100") == (0.0, 5000.0, 100.0)
    assert _parse_log_message("5000i 100e") == (0.0, 5000.0, 100.0)


# --- Positional (bare numbers) ---

def test_positional_one():
    """Single bare number → hours."""
    assert _parse_log_message("4") == (4.0, 0.0, 0.0)


def test_positional_two():
    """Two bare numbers → hours, income."""
    assert _parse_log_message("4 5000") == (4.0, 5000.0, 0.0)


def test_positional_three():
    """Three bare numbers → hours, income, expense."""
    assert _parse_log_message("4 5000 100") == (4.0, 5000.0, 100.0)


def test_positional_overflow():
    """Extra positional values beyond 3 are ignored."""
    assert _parse_log_message("4 5000 100 200") == (4.0, 5000.0, 100.0)
    assert _parse_log_message("4 5000 100 200 300") == (4.0, 5000.0, 100.0)


# --- Mixed explicit + positional ---

def test_explicit_hours_plus_positional():
    """Explicit hours + positional income and expense."""
    assert _parse_log_message("4h 5000") == (4.0, 5000.0, 0.0)
    assert _parse_log_message("4h 5000 100") == (4.0, 5000.0, 100.0)


def test_explicit_income_plus_positional():
    """Explicit income + positional hours and expense."""
    assert _parse_log_message("i4000 4") == (4.0, 4000.0, 0.0)
    assert _parse_log_message("i4000 4 100") == (4.0, 4000.0, 100.0)
    # Income explicit with positionals before it
    assert _parse_log_message("5000i 4 100") == (4.0, 5000.0, 100.0)


def test_explicit_expense_plus_positional():
    """Explicit expense + positional hours and income."""
    assert _parse_log_message("e100 4") == (4.0, 0.0, 100.0)
    assert _parse_log_message("e100 4 5000") == (4.0, 5000.0, 100.0)
    # Expense explicit with positionals after income
    assert _parse_log_message("4 5000 e100") == (4.0, 5000.0, 100.0)


def test_mixed_hours_income_explicit_expense_positional():
    """Hours + income explicit, expense positional."""
    assert _parse_log_message("4h i5000 100") == (4.0, 5000.0, 100.0)


def test_mixed_income_expense_explicit_hours_positional():
    """Income + expense explicit, hours positional."""
    assert _parse_log_message("4 i5000 e100") == (4.0, 5000.0, 100.0)


def test_income_explicit_hours_expense_positional():
    """Income explicit, hours + expense positional."""
    assert _parse_log_message("5000i 4 100") == (4.0, 5000.0, 100.0)


# --- Token order independence ---

def test_token_order():
    """Order of explicit tokens doesn't matter."""
    assert _parse_log_message("i5000 4h e100") == (4.0, 5000.0, 100.0)
    assert _parse_log_message("e100 4h i5000") == (4.0, 5000.0, 100.0)
    assert _parse_log_message("4h e100 i5000") == (4.0, 5000.0, 100.0)


# --- Edge case: unrecognized token mid-stream ---

def test_unrecognized_mid_stream():
    """Any unrecognized token → None even if others are valid."""
    assert _parse_log_message("4 abc 5000") is None
    assert _parse_log_message("4h xyz") is None


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
    """Empty or whitespace-only input → None."""
    assert _fuzzy_match_clinic("", CLINICS) is None
    assert _fuzzy_match_clinic("   ", CLINICS) is None
    assert _fuzzy_match_clinic("\t", CLINICS) is None


def test_fuzzy_exact_match():
    """Exact match (case-insensitive, space-insensitive)."""
    assert _fuzzy_match_clinic("Vela Yim", CLINICS) == CLINICS[0]
    assert _fuzzy_match_clinic("vela yim", CLINICS) == CLINICS[0]
    assert _fuzzy_match_clinic("VELA YIM", CLINICS) == CLINICS[0]
    assert _fuzzy_match_clinic("Velayim", CLINICS) == CLINICS[0]
    assert _fuzzy_match_clinic("velayim", CLINICS) == CLINICS[0]
    assert _fuzzy_match_clinic("Smile Dental", CLINICS) == CLINICS[1]
    assert _fuzzy_match_clinic("smiledental", CLINICS) == CLINICS[1]


def test_fuzzy_substring_match():
    """Input is substring of clinic name or vice versa."""
    # "vela" is substring of "velayim" (normalized)
    assert _fuzzy_match_clinic("vela", CLINICS) == CLINICS[0]
    # "yim" is substring of "velayim"
    assert _fuzzy_match_clinic("yim", CLINICS) == CLINICS[0]
    # "smile" is substring of "smiledental"
    assert _fuzzy_match_clinic("smile", CLINICS) == CLINICS[1]
    # "dental" is substring of "smiledental"
    assert _fuzzy_match_clinic("dental", CLINICS) == CLINICS[1]


def test_fuzzy_levenshtein_match():
    """Close matches within 30% edit distance."""
    # "vela yum" → "velayim": edit distance 2, len 7 → 0.286 ≤ 0.3
    assert _fuzzy_match_clinic("vela yum", CLINICS) == CLINICS[0]
    # "smil dental" → "smiledental": edit dist 1, len 11 → 0.09 ≤ 0.3
    assert _fuzzy_match_clinic("smil dental", CLINICS) == CLINICS[1]
    # "vela" already covered by substring, but also qualifies as levenshtein
    # "bangkok smile" no-space → "bangkoksmile" vs "bangkoksmile" = exact
    assert _fuzzy_match_clinic("Bangkok Smile", CLINICS) == CLINICS[2]


def test_fuzzy_no_match():
    """Far-away unmatched input → None."""
    assert _fuzzy_match_clinic("zzzzzz", CLINICS) is None
    assert _fuzzy_match_clinic("tooth fairy", CLINICS) is None
    assert _fuzzy_match_clinic("abcdef", CLINICS) is None


def test_fuzzy_single_clinic():
    """Works with single-clinic list."""
    single = [{"name": "Only Clinic", "id": 99}]
    assert _fuzzy_match_clinic("onlyclinic", single) == single[0]
    assert _fuzzy_match_clinic("only clinic", single) == single[0]
    assert _fuzzy_match_clinic("nope", single) is None


def test_fuzzy_empty_clinic_list():
    """Empty clinic list → None."""
    assert _fuzzy_match_clinic("anything", []) is None


# =============================================================================
# run
# =============================================================================

if __name__ == "__main__":
    import pytest
    # Run with verbose output and branch coverage if pytest-cov installed
    args = ["-v", __file__]
    try:
        import pytest_cov
        args.insert(0, "--cov=app")
        args.insert(1, "--cov-branch")
    except ImportError:
        pass
    sys.exit(pytest.main(args))
