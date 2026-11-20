"""Normalizing law-report citations such as ``2005 SCMR 890`` or ``2026 PLC(CS) 1296``.

Judgments write the same reporter several ways (``PLC (C.S.)``, ``PLC(CS)``,
``SCM R``, ``PLD 1999 S.C.``). ``citation_key`` gives one comparable form so a
precedent can be matched to a judgment in the corpus even without a site ID.
"""

from __future__ import annotations

import re

_REPLACEMENTS = (
    (r"\bSCM\s+R\b", "SCMR"),
    (r"\bSUPREME\s+COURT\b", "SC"),
    (r"\bS\s*C\b", "SC"),
    (r"\bKAR\b", "KARACHI"),
    (r"\bLAH\b", "LAHORE"),
    (r"\(\s*C\s*S\s*\)", "(CS)"),
    (r"\bTR\s*C\b", "TRC"),
    (r"\(\s*SERVICES?\s*\)", "(SERVICES)"),
)


def citation_key(citation: str) -> str:
    """Return a canonical key: upper case, no dots, single spaces, known
    reporter spellings unified."""
    s = citation.upper().replace(".", " ")
    s = re.sub(r"\s+", " ", s).strip()
    for pattern, repl in _REPLACEMENTS:
        s = re.sub(pattern, repl, s)
    s = re.sub(r"\s*\(", " (", s)
    return re.sub(r"\s+", " ", s).strip()
