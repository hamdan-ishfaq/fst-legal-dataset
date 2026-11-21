"""Parsing rules out of ESTACODE (Establishment Division, Edition 2021).

Each set of rules is printed between "These rules may be called ..." and an
``[Authority:- ... S.R.O. ..., dated ...]`` line naming the notification that
made them. Rule numbers stand alone (``3.``) or carry a short heading
(``1. Short title.-``). Amendments are marked in the text with symbols
(``*[``, ``**[``, ``@[``) that point to footnotes printed below a blank rule
line at the foot of the same page. A few markers were lost in the PDF; their
footnotes cannot be tied to a rule and are kept as unplaced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .statutes import StatuteUnit

MAX_UNIT_GAP = 3

_HEADER = re.compile(r"ESTACODE \(EDITION-\d{4}\)")
_SEPARATOR = re.compile(r"^\s{20,}$")
_START = re.compile(r"rules may be called|Short title", re.IGNORECASE)
_AUTHORITY = re.compile(r"^\[Authority")
_UNIT = re.compile(r"^(?:[*@#]+\s*\[?\s*)?(\d{1,3})(?:-?([A-Z]))?\.\s*(.*)$")
_HEADING = re.compile(r"^([A-Z][^.()\[\]]{2,90}?)\s*\.\s*[-–—]")
_BODY_MARK = re.compile(r"([*@#]+)\s*\[")
_FOOT_MARK = re.compile(r"^([*@#]+)\s*(\S.*)$")
_AMEND_WORD = re.compile(
    r"^(Subs|Substituted|Added|Ins|Inserted|Omitted|Renumbered|Re-numbered|Amended|Deleted)\b",
    re.IGNORECASE)


@dataclass
class RuleSet:
    units: list[StatuteUnit]
    unplaced_footnotes: list[str] = field(default_factory=list)
    authority: str = ""  # the notification that made the rules


def _clean(text: str) -> str:
    # Symbol-font characters (U+F020-U+F07E) stand for the ASCII character
    # with the same low byte; the amendment marks "*" and "@" come through so.
    text = re.sub("[-]", lambda m: chr(ord(m.group()) - 0xF000), text)
    text = text.replace("�", "—").replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip()


def _pages(doc: pymupdf.Document, first: int, last: int):
    """(body lines, footnote lines) per page; page numbers are 1-based."""
    for number in range(first, last + 1):
        body: list[str] = []
        notes: list[str] = []
        target = body
        for raw in str(doc[number - 1].get_text()).splitlines():
            if _SEPARATOR.match(raw):
                target = notes
                continue
            line = _clean(raw)
            if line and not _HEADER.search(line):
                target.append(line)
        yield body, notes


def _footnotes(lines: list[str]) -> list[tuple[str | None, str]]:
    """(marker, text); a footnote whose marker was lost has marker None."""
    out: list[tuple[str | None, str]] = []
    for line in lines:
        if m := _FOOT_MARK.match(line):
            out.append((m.group(1), m.group(2)))
        elif _AMEND_WORD.match(line) or not out:
            out.append((None, line))
        else:
            marker, text = out[-1]
            out[-1] = (marker, f"{text} {line}")
    return out


def _unit_start(line: str, last: int, last_number: str) -> tuple[str, str, str] | None:
    m = _UNIT.match(line)
    if not m:
        return None
    n, suffix, rest = int(m.group(1)), m.group(2) or "", m.group(3)
    number = f"{n}{suffix}"
    if number == last_number or not (last < n <= last + MAX_UNIT_GAP or (suffix and n == last)):
        return None
    heading = _HEADING.match(rest)
    return number, heading.group(1).strip() if heading else "", f"{number}. {rest}".strip()


def parse_estacode(pdf_path: str | Path, act_id: str, first_page: int, last_page: int) -> RuleSet:
    doc = pymupdf.open(pdf_path)
    result = RuleSet([])
    units = result.units
    started = done = False
    on_first_page = True
    last, pending = 0, ""
    for body, notes in _pages(doc, first_page, last_page):
        if done:
            break
        markers: dict[str, StatuteUnit] = {}
        for line in body:
            if not started:
                if not _START.search(line):
                    continue
                started = True
                if not _UNIT.match(line):
                    line = f"1. {line}"
            if _AUTHORITY.match(line):
                result.authority = line.strip("[]. ")
                done = True
                break
            if pending:  # a rule number printed alone on its line
                line, pending = f"{pending} {line}", ""
            if re.fullmatch(r"(?:[*@#]+\s*\[?\s*)?\d{1,3}(?:-?[A-Z])?\.", line):
                pending = line
                continue
            unit = _unit_start(line, last, units[-1].number if units else "")
            if unit:
                number, title, text = unit
                last = int(number.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
                units.append(StatuteUnit(act_id, number, title, "", text))
            elif units:
                units[-1].text += "\n" + line
            if units:
                for marker in _BODY_MARK.findall(line):
                    markers[marker] = units[-1]
        if not started:
            continue
        for marker, text in _footnotes(notes):
            if marker in markers:
                markers[marker].footnotes.append(text)
            elif not on_first_page:
                result.unplaced_footnotes.append(text)
        # Unplaced notes on the first page may belong to the text before the rules.
        on_first_page = False
    return result
