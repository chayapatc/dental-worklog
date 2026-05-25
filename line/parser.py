"""Backward-compatible re-exports from core/parser.py.

Prefer importing from core.parser directly for new code.
"""

from core.parser import fuzzy_match_clinic as _fuzzy_match_clinic
from core.parser import parse_log_message as _parse_log_message
