"""Parsing Acts and rules into numbered units (sections or rules).

Written for the Pakistan Code PDF layout: a contents list, then the body in
which each unit starts on a new line as ``4. Appeals to tribunals.—(1) ...``,
with amendment footnotes at the foot of each page. Inserted units carry their
footnote marker in front (``1[4A. Review.⎯ ...``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .laws import ACTS_BY_ID

MAX_UNIT_GAP = 4  # largest jump in unit numbers accepted as the next unit

_UNIT_START = re.compile(
    r"^(?:\d{1,2}\[)?(\d{1,3})\s?([A-Z]{0,2})\.\s+(?P<rest>(?:\d{1,2}\[)?[A-Z\[].*)$")
_TITLE = re.compile(r"^\[?([^—⎯_]{2,150}?)\s*\.?\s*(?:—|⎯|_{2,}|\.\s|\.$|-{2}|\])")
_CHAPTER = re.compile(r"^CHAPTER\s+([IVXLC]+)\b", re.IGNORECASE)
_FOOTNOTE = re.compile(
    r"^\d{1,2}\s*(?:Subs|Ins|Added|Omitted|For\b|Rep|See|Re-?numbered|The\s+words|Words|"
    r"Clause|Sub-section|Proviso|Section|Shall|New)", re.IGNORECASE)
_UNNUMBERED_HEADING = re.compile(
    r"^((?:[A-Z][a-z]+|[a-z]+|of|and|or|to|the|in|by|for|on|with|\d+)"
    r"(?:[ ,-]+(?:[A-Za-z]+|\d+)){0,9})\s*\.\s*(?:—|-{2}|\.-|⎯)")
_NOISE = re.compile(r"^(Page \d+ of \d+|Updated till .*)$")
_FOOTNOTE_MARK = re.compile(r"(?<![\w\]])\d{1,2}(?=\[)")


@dataclass
class StatuteUnit:
    act_id: str
    number: str  # "4", "4A"
    title: str
    chapter: str
    text: str
    footnotes: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.act_id}:{ACTS_BY_ID[self.act_id].unit_kind}-{self.number}"

    @property
    def omitted(self) -> bool:
        return bool(re.match(r"^\S+\s+\[?\s*Omitted", self.text, re.IGNORECASE))


def _clean(text: str) -> str:
    text = text.replace(";", ";").replace("�", "—")
    text = _FOOTNOTE_MARK.sub("", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _lines(pdf_path: str | Path, header: str, noise: re.Pattern | None) -> list[str]:
    doc = pymupdf.open(pdf_path)
    lines = []
    for page in doc:
        for raw in str(page.get_text()).splitlines():
            line = raw.strip()
            if (not line or _NOISE.match(line) or line.upper().rstrip(".") == header
                    or (noise and noise.search(line))):
                continue
            lines.append(line)
    return lines


def _join_wrapped_headings(lines: list[str]) -> list[str]:
    """Pakistan Code sometimes prints ``4.`` on its own line before the text;
    join such a bare number with the next line."""
    out: list[str] = []
    for line in lines:
        if out and re.fullmatch(r"(?:\d{1,2}\[)?\d{1,3}\s?[A-Z]{0,2}\.", out[-1]):
            out[-1] = f"{out[-1]} {line}"
        elif out and _heading_continues(out[-1], line):
            out[-1] = f"{out[-1]} {line}"
        else:
            out.append(line)
    return out


_HEADING_END = re.compile(r"\.?\s*(?:—|⎯|_{2,}|-{2}|\.-)")


def _heading_continues(previous: str, line: str) -> bool:
    """A numbered heading wrapped onto the next line: "9. Procedure to be
    followed by authority where inquiry is" + "necessary.—(1) ..."."""
    return (bool(re.match(r"^(?:\d{1,2}\[)?\d{1,3}\s?[A-Z]{0,2}\.\s+[A-Z]", previous))
            and not _HEADING_END.search(previous)
            and len(previous) < 90
            and bool(_HEADING_END.search(line[:60])))


def _unit_start(line: str, last: int, previous: str) -> tuple[str, str, str] | None:
    """(number, title, cleaned text) if the line starts the next unit."""
    m = _UNIT_START.match(line)
    if not m:
        return None
    number = m.group(1) + m.group(2)
    rest = _clean(m["rest"])
    title = _TITLE.match(rest)
    if not title or not last <= int(m.group(1)) <= last + MAX_UNIT_GAP:
        return None
    if number == previous:  # a misprinted repeat of the last number
        return None
    return number, title.group(1).strip().rstrip("."), f"{number}. {rest}"


def _unnumbered_start(line: str) -> str | None:
    """Title of a unit whose number was lost in scanning ("Appeal.—A civil
    servant ..."), else None."""
    m = _UNNUMBERED_HEADING.match(line)
    return m.group(1).strip() if m else None


def parse_statute(
    pdf_path: str | Path,
    act_id: str,
    header: str,
    noise: re.Pattern | None = None,
    unnumbered_headings: bool = False,
) -> list[StatuteUnit]:
    """Parse one Act or set of rules.

    ``header`` is the running title printed on each page (e.g. ``THE SERVICE
    TRIBUNALS ACT, 1973``) and is dropped, as is any line matching ``noise``.
    ``unnumbered_headings`` is for scanned texts where OCR lost some unit
    numbers: a line that starts with a heading ("Appeal.—") then starts the
    next unit in sequence."""
    lines = _join_wrapped_headings(_lines(pdf_path, header.upper().rstrip("."), noise))

    # The body starts at the last "1. Short title" line; an earlier one is in
    # the contents list. Scanned texts may have lost the number.
    starts = [i for i, ln in enumerate(lines)
              if re.match(r"^(?:\d{1,2}\[)?(?:1\.\s+)?Short title", ln)]
    body = lines[starts[-1]:] if starts else lines

    units: list[StatuteUnit] = []
    chapter = ""
    last = 0
    for line in body:
        if _FOOTNOTE.match(line):
            if units:
                units[-1].footnotes.append(_clean(line))
            continue
        if m := _CHAPTER.match(line):
            chapter = m.group(1).upper()
            continue
        unit = _unit_start(line, last, units[-1].number if units else "")
        if not unit and unnumbered_headings and (title := _unnumbered_start(line)):
            number = str(last + 1)
            unit = number, title, f"{number}. {_clean(line)}"
        if unit:
            number, title, text = unit
            last = int(number.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
            units.append(StatuteUnit(act_id, number, title, chapter, text))
        elif units:
            units[-1].text += "\n" + _clean(line)
    return units
