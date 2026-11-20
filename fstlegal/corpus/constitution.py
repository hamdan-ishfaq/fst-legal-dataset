"""Parsing the consolidated Constitution PDF into one unit per Article.

Each printed page has a running header, a body column, a margin holding the
Article titles (right on odd pages, left on even pages), and amendment
footnotes below a rule. Text is read line by line and lines are told apart by
position. An Article starts at a body line that begins with the next number in
sequence ("212. (1) ...").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

ACT_ID = "CONST-1973"

MARGIN_RIGHT_X0 = 455  # odd pages: margin titles start right of this
MARGIN_LEFT_X1 = 160  # even pages: margin titles end left of this
HEADER_Y = 100  # the running header sits above this
SAME_LINE_DY = 3  # pieces of text this close vertically are one printed line
TITLE_GAP_DY = 14  # margin lines closer than this belong to one title
MAX_ARTICLE_GAP = 6  # largest jump in Article numbers accepted as the next Article

# The number can carry a footnote marker in front ("1272." is Article 272 with
# footnote 1), so up to five digits are read and the marker is cut later.
_ARTICLE_START = re.compile(r"^(\d{1,5})([A-Z]{0,3})\.(?=\s|\[|\d{1,2}\[)")
_LEADING_MARK = re.compile(r"^(?:\d{0,2}\[)+")
_PART = re.compile(r"^PART\s+([IVXLC]+[A-Z]?)$")
_CHAPTER = re.compile(r"^CHAPTER\s+(\d+[A-Z]?)\b", re.IGNORECASE)
_SCHEDULE = re.compile(r"^(?:\d{1,2}\[)?\[?FIRST SCHEDULE", re.IGNORECASE)
_RULE = re.compile(r"^[�_]{20,}")
_FOOTNOTE_MARK = re.compile(r"(?<![\w\]])\d{1,2}(?=\[)")
_OMISSION = re.compile(r"^\d{0,2}\*(\s*\*)*$")


@dataclass
class Article:
    number: str  # "10A", "212"
    title: str
    part: str
    chapter: str
    text: str
    page: int  # 0-based page index in the PDF
    footnotes: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{ACT_ID}:art-{self.number}"

    @property
    def omitted(self) -> bool:
        return bool(re.search(r"\bOmitted\b", self.text[:200], re.IGNORECASE))


@dataclass
class _Line:
    x0: float
    x1: float
    y0: float
    text: str


def _clean(text: str) -> str:
    text = text.replace("�", "—")
    text = _FOOTNOTE_MARK.sub("", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _lines(page) -> list[_Line]:
    """Printed lines of a page in reading order."""
    raw: list[_Line] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"])
            if text.strip():
                x0, y0, x1, _ = line["bbox"]
                raw.append(_Line(x0, x1, y0, text))
    raw.sort(key=lambda ln: (round(ln.y0), ln.x0))
    return raw


def _split_page(page) -> tuple[list[_Line], list[list[_Line]], list[str]]:
    """Body lines, margin title groups and footnote texts of one page."""
    lines = _lines(page)
    rule_y = min((ln.y0 for ln in lines if _RULE.match(ln.text.strip())), default=float("inf"))
    body: list[_Line] = []
    margin: list[_Line] = []
    notes: list[str] = []
    for ln in lines:
        text = ln.text.strip()
        if _RULE.match(text):
            continue
        if ln.y0 < HEADER_Y and ("CONSTITUTION OF PAKISTAN" in text or text.isdigit()):
            continue
        if ln.y0 > rule_y:
            notes.append(_clean(text))
        elif ln.x0 >= MARGIN_RIGHT_X0 or ln.x1 <= MARGIN_LEFT_X1:
            margin.append(ln)
        elif body and abs(ln.y0 - body[-1].y0) < SAME_LINE_DY:
            body[-1].text += " " + ln.text
        else:
            body.append(_Line(ln.x0, ln.x1, ln.y0, ln.text))

    groups: list[list[_Line]] = []
    for ln in sorted(margin, key=lambda m: m.y0):
        if groups and ln.y0 - groups[-1][-1].y0 < TITLE_GAP_DY:
            groups[-1].append(ln)
        else:
            groups.append([ln])
    return body, groups, _join_footnotes(notes)


def _join_footnotes(lines: list[str]) -> list[str]:
    """Footnotes start with their number ("3Subs. by ..."); other lines continue
    the previous footnote."""
    notes: list[str] = []
    for text in lines:
        if re.match(r"^\d{1,2}\s*[A-Z]", text) or not notes:
            notes.append(text)
        else:
            notes[-1] += " " + text
    return notes


def _title_for(y: float, groups: list[list[_Line]]) -> str:
    near = [g for g in groups if y - 20 <= g[0].y0 <= y + 40]
    if not near:
        return ""
    best = min(near, key=lambda g: abs(g[0].y0 - y))
    title = _clean(" ".join(ln.text.strip() for ln in best))
    title = re.sub(r"^\d{1,2}\*\s*", "", title)  # omission marker printed in the margin
    title = re.sub(r"(\w)- ([a-z])", r"\1\2", title)  # word broken across lines
    return re.sub(r"(\w)- ([A-Z])", r"\1-\2", title)  # hyphenated name broken across lines


def _article_start(text: str, last: int) -> tuple[str, str] | None:
    """(Article number, text from the number on) if this line starts the next
    Article, else None.

    Footnote markers print right before the number: "10[2A." is Article 2A
    inserted by footnote 10, and "11." can be Article 1 with footnote 1. The
    reading that continues the sequence wins."""
    text = _LEADING_MARK.sub("", text.strip(), count=1)
    m = _ARTICLE_START.match(text)
    if not m:
        return None
    digits, letters = m.group(1), m.group(2)
    for cut in range(len(digits)):
        candidate = digits[cut:]
        if len(candidate) <= 3 and last <= int(candidate) <= last + MAX_ARTICLE_GAP:
            return candidate + letters, text[cut:]
    return None


def parse_constitution(pdf_path: str | Path) -> list[Article]:
    doc = pymupdf.open(pdf_path)
    articles: list[Article] = []
    part = chapter = ""
    last_num = 0
    started = False
    page_notes: dict[int, list[str]] = {}

    for index in range(doc.page_count):
        body, titles, notes = _split_page(doc[index])
        page_notes[index] = notes
        for ln in body:
            text = ln.text.strip()
            if m := _PART.match(text):
                part = m.group(1)
                continue
            if not started:
                if "Pakistan shall be Federal Republic" not in text:
                    continue
                started = True
            if _SCHEDULE.match(text):
                return _attach_notes(articles, page_notes)
            if m := _CHAPTER.match(text):
                chapter = m.group(1)
                continue
            if _OMISSION.match(text):
                continue
            found = _article_start(text, last_num)
            if found:
                number, rest = found
                last_num = int(number.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
                omitted_title = re.match(r"\S+\s+\[([^\]]+)\]\s+Omitted", rest)
                articles.append(Article(
                    number=number,
                    title=_title_for(ln.y0, titles) or (
                        omitted_title.group(1) if omitted_title else ""),
                    part=part,
                    chapter=chapter,
                    text=_clean(rest),
                    page=index,
                ))
            elif articles:
                articles[-1].text += "\n" + _clean(text)
    return _attach_notes(articles, page_notes)


def _attach_notes(articles: list[Article], page_notes: dict[int, list[str]]) -> list[Article]:
    """Give each Article the amendment footnotes printed on the pages it spans."""
    for i, art in enumerate(articles):
        end = articles[i + 1].page if i + 1 < len(articles) else art.page
        for p in range(art.page, end + 1):
            art.footnotes.extend(page_notes.get(p, []))
    return articles
