"""Amendment history read from the footnotes of a statute text.

Official texts print the current wording and note each change in a footnote:
``Subs. vide ... S.R.O. No. 742(I)/2002, dated 28-10-2002`` (ESTACODE) or
``Subs. by the Service Tribunals (Amdt.) Act, 1997 (XVII of 1997), s. 2``
(Pakistan Code). The earlier wording is not printed, so the history records
what changed and when, not the old text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_KINDS = (
    ("substituted", r"subs(?:tituted)?\b"),
    ("inserted", r"ins(?:erted)?\b"),
    ("added", r"added\b"),
    ("omitted", r"omitted\b|deleted\b|rep(?:ealed)?\b"),
    ("renumbered", r"re-?numbered\b"),
)
_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), start=1)}
_NUMERIC_DATE = re.compile(r"(\d{1,2})[-./](\d{1,2})[-./](\d{2,4})")
_WORD_DATE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+),?\s+(\d{4})")
_DATED = re.compile(r"dated\s+(?:the\s+)?(.{0,30})", re.IGNORECASE)
_WEF = re.compile(r"w\.\s?e\.\s?f\.?\s*([\d./-]+\d)", re.IGNORECASE)
_INSTRUMENT = re.compile(
    r"(S\.?\s?R\.?\s?O\.?\s*(?:No\.?\s*)?[\w()]+/\d{2,4}"
    r"|(?:Ord|Act|P\.\s?O)\.?\s*No\.?\s*[IVXLC\d]+\s+of\s+\d{4}"
    r"|Notification\s+No\.?\s*[\w/.()-]+\w"
    r"|[A-Z][\w ().&'-]*?Act,?\s*[IVXLC]+\s+of\s+\d{4}"
    r"|[A-Z][\w ().&,'-]*?(?:Act|Ordinance|Order|Amendment)\b,?\s*\d{4}(?:\s*\([^)]*\))?)")
_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")


@dataclass(frozen=True)
class Amendment:
    kind: str
    instrument: str
    date: str | None  # ISO date the change was made, when printed
    effective: str | None  # ISO date it took effect from, when it differs
    year: int | None  # year of the change, from the date or the instrument
    note: str


def _iso(text: str) -> str | None:
    if m := _NUMERIC_DATE.search(text):
        d, mth, y = (int(g) for g in m.groups())
        y += 1900 if y >= 50 and y < 100 else 2000 if y < 50 else 0
    elif (m := _WORD_DATE.search(text)) and m.group(2).lower() in _MONTHS:
        d, mth, y = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
    else:
        return None
    try:
        return date(y, mth, d).isoformat()
    except ValueError:
        return None


def parse_amendment(note: str) -> Amendment | None:
    """The amendment a footnote records, or None for an explanatory note."""
    text = re.sub(r"^[\d*@#]+\s*", "", note.strip())
    head = text[:40].lower()
    kind = next((k for k, pattern in _KINDS if re.match(pattern, head)), None)
    if kind is None:
        return None
    instrument = _INSTRUMENT.search(re.sub(r"^\S+\s+(?:by|vide)\s+(?:the\s+)?", "", text))
    dated = _DATED.search(text)
    made = _iso(dated.group(1)) if dated else None
    wef = _WEF.search(text)
    effective = _iso(wef.group(1)) if wef else None
    year_source = made or (instrument.group(1) if instrument else text)
    year = _YEAR.search(year_source)
    if year is None and instrument and (short := re.search(r"/(\d{2})\b", instrument.group(1))):
        y = int(short.group(1))
        year_value: int | None = y + (1900 if y >= 50 else 2000)
    else:
        year_value = int(year.group(1)) if year else None
    return Amendment(kind, instrument.group(1).strip() if instrument else "", made,
                     effective if effective != made else None, year_value, text)
