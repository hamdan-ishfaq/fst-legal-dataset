"""Splitting judgments and statute units into retrieval chunks.

Judgment chunks follow paragraph boundaries so a citation can point at
paragraph numbers. Statute chunks are one unit each, split at sub-section
markers only when a unit is too long.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_WORDS = 350  # target upper size of a chunk

_SENTENCE = re.compile(r"(?<=[.;:])\s+(?=[A-Z(\d])")
_SUBSECTION = re.compile(r"\n(?=\(\d+[A-Z]?\)\s)")


@dataclass
class Chunk:
    id: str
    kind: str  # "judgment" or "statute"
    source_id: str  # judgment ID or statute-unit ID
    para_from: int | None
    para_to: int | None
    text: str


def _words(text: str) -> int:
    return len(text.split())


def _split_long(text: str, pattern: re.Pattern) -> list[str]:
    """Split text at ``pattern`` into pieces of at most MAX_WORDS, falling back
    to sentence boundaries for any piece still too long."""
    pieces: list[str] = []
    current = ""
    for part in pattern.split(text):
        if current and _words(current) + _words(part) > MAX_WORDS:
            pieces.append(current.strip())
            current = ""
        current += (" " if current else "") + part
    if current.strip():
        pieces.append(current.strip())
    if pattern is not _SENTENCE:
        out: list[str] = []
        for p in pieces:
            out.extend(_split_long(p, _SENTENCE) if _words(p) > MAX_WORDS else [p])
        return out
    return pieces


def judgment_chunks(judgment_id: str, paragraphs) -> list[Chunk]:
    """Group consecutive paragraphs into chunks of up to MAX_WORDS words."""
    chunks: list[Chunk] = []
    group: list = []

    def flush():
        if not group:
            return
        text = "\n\n".join(p.text for p in group)
        chunks.append(Chunk(f"{judgment_id}#p{group[0].number}-{group[-1].number}", "judgment",
                            judgment_id, group[0].number, group[-1].number, text))
        group.clear()

    for para in paragraphs:
        if _words(para.text) > MAX_WORDS:
            flush()
            for i, piece in enumerate(_split_long(para.text, _SENTENCE)):
                chunks.append(Chunk(f"{judgment_id}#p{para.number}.{i + 1}", "judgment",
                                    judgment_id, para.number, para.number, piece))
            continue
        if group and sum(_words(p.text) for p in group) + _words(para.text) > MAX_WORDS:
            flush()
        group.append(para)
    flush()
    return chunks


def statute_chunks(unit_id: str, header: str, text: str) -> list[Chunk]:
    """One chunk per unit, or several split at sub-sections. Each chunk starts
    with the unit header so it reads on its own."""
    pieces = [text] if _words(text) <= MAX_WORDS else _split_long(text, _SUBSECTION)
    if len(pieces) == 1:
        return [Chunk(unit_id, "statute", unit_id, None, None, f"{header}\n{pieces[0]}")]
    return [Chunk(f"{unit_id}#{i + 1}", "statute", unit_id, None, None, f"{header}\n{p}")
            for i, p in enumerate(pieces)]
