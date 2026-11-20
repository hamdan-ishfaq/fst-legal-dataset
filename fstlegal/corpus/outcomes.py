"""Normalizing the free-text outcome of a judgment to a fixed label."""

from __future__ import annotations

import re

LABELS = ("allowed", "partly_allowed", "dismissed", "disposed_of", "remanded", "withdrawn",
          "unknown")

# First match wins, so the more specific wordings come first.
_RULES: tuple[tuple[str, str], ...] = (
    (r"\b(partly|partially|partial)\b", "partly_allowed"),
    (r"\bremand", "remanded"),
    (r"\bwithdrawn\b", "withdrawn"),
    (r"\b(allowed|accepted|succeeds?|set aside)\b", "allowed"),
    (r"\b(dismissed|rejected|regretted|not maintainable|fails?)\b", "dismissed"),
    (r"\b(disposed|order accordingly|infructuous|closed)\b", "disposed_of"),
)


def normalize_outcome(raw: str | None) -> str:
    """Map an outcome such as 'Appeal accepted.' to a label in LABELS."""
    if not raw or not str(raw).strip():
        return "unknown"
    text = str(raw).lower()
    for pattern, label in _RULES:
        if re.search(pattern, text):
            return label
    return "unknown"
