"""Loading clean judgments and splitting them into numbered paragraphs.

Input is ``dataset/fst_cases_clean.csv`` (built by ``dataset/clean_dataset.py``).
One judgment can be reported under several citations; rows are grouped by the
source site ID so each judgment appears once.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .citations import citation_key
from .laws import LawRef, resolve

# A paragraph marker: "12. " after the end of a sentence, followed by a capital
# letter or an opening bracket.
_PARA_MARK = re.compile(r"(?:(?<=[.:;)\]])|^)\s*(\d{1,3})\.\s+(?=[A-Z(\"'])")

# Words that appear in an operative order ("the appeal is dismissed").
_DISPOSAL = re.compile(
    r"\b(allow(?:ed|ing)|dismiss(?:ed|ing)|dispos(?:ed|ing) of|accept(?:ed|ing)|set[- ]aside|"
    r"remand(?:ed|ing)|regretted|order accordingly|stands vacated|reinstated)\b",
    re.IGNORECASE)

_SENTENCE_END = re.compile(r"(?<=[.:;])\s+(?=\d{1,3}\.\s|[A-Z(])")
_OPERATIVE_SENTENCES = 12  # how far back from the end the disposal is looked for

# Phrases a complete FST judgment ends with.
_CLOSING = re.compile(
    r"(no order as to cost|parties (?:may |shall |be )?(?:be )?informed|"
    r"announced|file be consigned|order accordingly|disposed of)", re.IGNORECASE)


@dataclass
class Precedent:
    citation: str
    key: str
    site_id: int | None


@dataclass
class Paragraph:
    number: int  # 1 for the opening paragraph, which has no number in the text
    text: str


@dataclass
class Judgment:
    site_id: int
    citations: list[str]
    title: str
    petitioner: str
    respondent: str
    year: int | None
    decision_date: str | None
    appeal_number: str | None
    bench: list[str]
    outcome: str
    summary: str
    questions: list[str]
    keywords: list[str]
    law_refs: list[LawRef]
    precedents: list[Precedent]
    full_text: str
    text_truncated: bool
    source_url: str
    paragraphs: list[Paragraph] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"J-{self.site_id}"

    @property
    def operative_order(self) -> str:
        """The closing sentences that state the disposal, starting from the
        first sentence with disposal wording among the last few. Empty when the
        text is truncated or no disposal wording is found near the end."""
        if self.text_truncated:
            return ""
        sentences = _SENTENCE_END.split(self.full_text)[-_OPERATIVE_SENTENCES:]
        for i, s in enumerate(sentences):
            if _DISPOSAL.search(s):
                return " ".join(sentences[i:]).strip()
        return ""


def split_paragraphs(text: str) -> list[Paragraph]:
    """Split on paragraph numbers. Only a marker that continues the sequence
    (the next number, or up to two skipped) starts a new paragraph, so numbered lists
    inside a paragraph are not mistaken for paragraph breaks."""
    paras: list[Paragraph] = []
    start, current = 0, 1
    for m in _PARA_MARK.finditer(text):
        n = int(m.group(1))
        if current < n <= current + 3:
            chunk = text[start:m.start()].strip()
            if chunk:
                paras.append(Paragraph(current, chunk))
            start, current = m.start(1), n
    tail = text[start:].strip()
    if tail:
        paras.append(Paragraph(current, tail))
    return paras


def looks_truncated(text: str) -> bool:
    """True when the last part of a judgment has none of the usual closing
    phrases. A heuristic; the manual flag from the cleaning step wins."""
    end = text[-600:]
    return not (_CLOSING.search(end) or _DISPOSAL.search(end[-300:]))


def _json_list(value) -> list:
    if not isinstance(value, str) or not value.strip():
        return []
    return json.loads(value)


def load_judgments(csv_path: str | Path) -> list[Judgment]:
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    judgments: list[Judgment] = []
    for _, rows in df.groupby("site_id", sort=False):
        r = rows.iloc[0]
        site_id = int(r["site_id"])
        text = r["full_text"]
        laws = [resolve(x.get("provision", ""), x.get("act", ""))
                for x in _json_list(r["laws_json"])]
        precedents = [
            Precedent(p["citation"], citation_key(p["citation"]),
                      int(p["site_id"]) if p.get("site_id") else None)
            for p in _json_list(r["precedents_json"])
        ]
        j = Judgment(
            site_id=site_id,
            citations=rows["citation"].tolist(),
            title=r["case_name_full"] if isinstance(r["case_name_full"], str) else r["case_name"],
            petitioner=r["petitioner"],
            respondent=r["respondent"],
            year=int(r["year"]) if pd.notna(r["year"]) else None,
            decision_date=r["decision_date"] if isinstance(r["decision_date"], str) else None,
            appeal_number=r["appeal_number"] if isinstance(r["appeal_number"], str) else None,
            bench=_json_list(r["bench_members"]),
            outcome=r["outcome"],
            summary=r["summary"],
            questions=_json_list(r["questions_json"]),
            keywords=[k.strip() for k in str(r["keywords"]).split(",") if k.strip()],
            law_refs=laws,
            precedents=precedents,
            full_text=text,
            text_truncated=bool(r.get("text_truncated", 0)) or looks_truncated(text),
            source_url=r["source_url"],
            paragraphs=split_paragraphs(text),
        )
        judgments.append(j)
    return judgments
