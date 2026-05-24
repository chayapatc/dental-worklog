"""LINE message parser and fuzzy clinic matcher."""

import re
from datetime import datetime, timezone, timedelta


def _fuzzy_match_clinic(input_name: str, clinics: list) -> dict | None:
    """Match user input to closest clinic name (case-insensitive, no spaces)."""
    clean = input_name.lower().replace(" ", "").strip()
    if not clean:
        return None

    # Build normalized clinic names
    normalized = [
        {"clinic": c, "clean": c["name"].lower().replace(" ", "")}
        for c in clinics
    ]

    # 1. Exact match on normalized name
    for n in normalized:
        if clean == n["clean"]:
            return n["clinic"]

    # 2. Input is substring of clinic name or vice versa
    for n in normalized:
        if clean in n["clean"] or n["clean"] in clean:
            return n["clinic"]

    # 3. Levenshtein distance — accept if edit distance <= 30% of longer string
    def levenshtein(a, b):
        if len(a) < len(b):
            return levenshtein(b, a)
        if len(b) == 0:
            return len(a)
        prev = range(len(b) + 1)
        for i, ca in enumerate(a):
            curr = [i + 1]
            for j, cb in enumerate(b):
                curr.append(min(
                    prev[j + 1] + 1,      # deletion
                    curr[j] + 1,            # insertion
                    prev[j] + (0 if ca == cb else 1),  # substitution
                ))
            prev = curr
        return prev[-1]

    best = None
    best_dist = 999
    for n in normalized:
        d = levenshtein(clean, n["clean"])
        max_len = max(len(clean), len(n["clean"]))
        if max_len > 0 and d / max_len <= 0.3 and d < best_dist:
            best = n["clinic"]
            best_dist = d

    return best


def _parse_log_message(text: str) -> tuple | None:
    """Parse a LINE message into (date_str, hours, income, expense) or None.
    
    Returns: (date_str, hours, income, expense) where date_str is "MM-DD"
             or None (caller defaults to today).

    Format: {hours} {income}i? {expense}e? {date}?
    - h suffix = hours (e.g. "4h")
    - i prefix/suffix = income (e.g. "i5000" or "5000i")
    - e prefix/suffix = expense (e.g. "e500" or "500e")
    - Bare numbers assigned positionally: hours, income, expense
    - d/m at end = date (e.g. "22/5" = 22 May this year)
    """
    tokens = text.strip().split()
    if not tokens:
        return None

    # Extract optional date (d/m or d alone — last token only)
    date_str = None
    # d/m pattern: "22/5" = May 22
    m = re.match(r'^(\d{1,2})/(\d{1,2})$', tokens[-1])
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        if 1 <= day <= 31 and 1 <= month <= 12:
            date_str = f"{month:02d}-{day:02d}"
            tokens = tokens[:-1]
    # d-alone pattern: "22" = 22nd this month (only with 3+ tokens to avoid ambiguity)
    elif len(tokens) >= 3 and re.match(r'^\d{1,2}$', tokens[-1]):
        day = int(tokens[-1])
        if 1 <= day <= 31:
            now = datetime.now(timezone(timedelta(hours=7)))
            date_str = f"{now.month:02d}-{day:02d}"
            tokens = tokens[:-1]

    if not tokens:
        return None  # only a date, no values

    hours = 0.0
    income = 0.0
    expense = 0.0
    has_explicit = {"hours": False, "income": False, "expense": False}
    positional = []

    for token in tokens:
        t = token.lower().strip()

        # h suffix: "4h", "0.5h"
        m = re.match(r'^(\d+(?:\.\d+)?)h$', t)
        if m:
            hours = float(m.group(1))
            has_explicit["hours"] = True
            continue

        # i prefix: "i5000"
        m = re.match(r'^i(\d+(?:\.\d+)?)$', t)
        if m:
            income = float(m.group(1))
            has_explicit["income"] = True
            continue

        # i suffix: "5000i"
        m = re.match(r'^(\d+(?:\.\d+)?)i$', t)
        if m:
            income = float(m.group(1))
            has_explicit["income"] = True
            continue

        # e prefix: "e500"
        m = re.match(r'^e(\d+(?:\.\d+)?)$', t)
        if m:
            expense = float(m.group(1))
            has_explicit["expense"] = True
            continue

        # e suffix: "500e"
        m = re.match(r'^(\d+(?:\.\d+)?)e$', t)
        if m:
            expense = float(m.group(1))
            has_explicit["expense"] = True
            continue

        # Pure number
        m = re.match(r'^(\d+(?:\.\d+)?)$', t)
        if m:
            positional.append(float(m.group(1)))
            continue

        # Unrecognized token
        return None

    # Assign positional values to unset fields
    pos_idx = 0
    if not has_explicit["hours"] and pos_idx < len(positional):
        hours = positional[pos_idx]; pos_idx += 1
    if not has_explicit["income"] and pos_idx < len(positional):
        income = positional[pos_idx]; pos_idx += 1
    if not has_explicit["expense"] and pos_idx < len(positional):
        expense = positional[pos_idx]; pos_idx += 1

    # Require at least one meaningful value
    if hours == 0 and income == 0 and expense == 0:
        return None

    return (date_str, hours, income, expense)

