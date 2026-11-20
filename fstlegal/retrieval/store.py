"""Read access to ``corpus.db``."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..corpus.build import DEFAULT_OUT


@dataclass
class ChunkHit:
    chunk_id: str
    kind: str  # "judgment" or "statute"
    source_id: str
    text: str
    score: float
    para_from: int | None = None
    para_to: int | None = None


class Corpus:
    """Thin read-only wrapper over the corpus database."""

    def __init__(self, path: str | Path = DEFAULT_OUT):
        self.path = Path(path)
        self.con = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True,
                                   check_same_thread=False)
        self.con.row_factory = sqlite3.Row

    @property
    def content_hash(self) -> str:
        return self.con.execute("SELECT value FROM meta WHERE key='content_hash'").fetchone()[0]

    def judgment(self, judgment_id: str) -> dict | None:
        row = self.con.execute("SELECT * FROM judgments WHERE id=?", (judgment_id,)).fetchone()
        if row is None:
            return None
        j = dict(row)
        for key in ("bench", "questions", "keywords"):
            j[key] = json.loads(j[key])
        j["citations"] = [r[0] for r in self.con.execute(
            "SELECT citation FROM citations WHERE judgment_id=?", (judgment_id,))]
        return j

    def judgment_ids(self) -> list[str]:
        return [r[0] for r in self.con.execute("SELECT id FROM judgments ORDER BY id")]

    def unit(self, unit_id: str) -> dict | None:
        row = self.con.execute("SELECT * FROM statute_units WHERE id=?", (unit_id,)).fetchone()
        if row is None:
            return None
        u = dict(row)
        u["footnotes"] = json.loads(u["footnotes"])
        return u

    def unit_ids(self) -> set[str]:
        return {r[0] for r in self.con.execute("SELECT id FROM statute_units")}

    def chunk(self, chunk_id: str) -> dict | None:
        row = self.con.execute("SELECT * FROM chunks WHERE id=?", (chunk_id,)).fetchone()
        return dict(row) if row else None

    def chunks(self) -> list[dict]:
        return [dict(r) for r in self.con.execute("SELECT * FROM chunks ORDER BY rowid")]

    def edges(self) -> list[tuple[str, str, str]]:
        return [tuple(r) for r in self.con.execute("SELECT src, rel, dst FROM edges")]

    def act_title(self, act_id: str) -> str | None:
        row = self.con.execute("SELECT title FROM acts WHERE id=?", (act_id,)).fetchone()
        return row[0] if row else None
