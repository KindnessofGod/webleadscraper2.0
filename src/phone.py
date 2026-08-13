"""Nigerian phone number normalization + structural validation (Stage D).

We validate structurally rather than against an exhaustive, fast-changing
network-prefix whitelist: normalize to +234XXXXXXXXXX and require a mobile
leading digit (7/8/9), which covers the MTN/Glo/Airtel/9mobile ranges used
by the vast majority of Nigerian SMEs listed on Google Maps.
"""
from __future__ import annotations

import re

_DIGITS_RE = re.compile(r"\d+")


def _digits_only(raw: str) -> str:
    return "".join(_DIGITS_RE.findall(raw or ""))


def normalize_phone(raw: str | None) -> str | None:
    """Return E.164-ish +234XXXXXXXXXX, or None if it can't be normalized."""
    if not raw:
        return None
    digits = _digits_only(raw)

    if digits.startswith("234") and len(digits) == 13:
        national = digits[3:]
    elif digits.startswith("0") and len(digits) == 11:
        national = digits[1:]
    elif len(digits) == 10:
        national = digits
    else:
        return None

    return f"+234{national}"


def is_valid_nigerian_phone(raw: str | None) -> bool:
    normalized = normalize_phone(raw)
    if not normalized:
        return False
    national = normalized[4:]  # strip '+234'
    return len(national) == 10 and national[0] in ("7", "8", "9")
