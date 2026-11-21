"""Build ``corpus.db``: judgments, statutes, chunks, links and full-text index.

Run with ``python -m fstlegal.corpus.build``. The database is rebuilt from the
source files every time, so the same sources always give the same corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import sources
from .amendments import parse_amendment
from .chunking import judgment_chunks, statute_chunks
from .citations import citation_key
from .constitution import parse_constitution
from .estacode import parse_estacode
from .judgments import Judgment, load_judgments
from .laws import ACTS, ACTS_BY_ID, REPLACEMENTS
from .statutes import StatuteUnit, parse_statute

DEFAULT_OUT = sources.ROOT / "data" / "build" / "corpus.db"

SCHEMA = """
CREATE TABLE acts (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, unit_kind TEXT NOT NULL,
    has_text INTEGER NOT NULL, edition TEXT, made_by TEXT, replaced_by TEXT, replaced_on TEXT
);
CREATE TABLE amendments (
    act_id TEXT NOT NULL REFERENCES acts(id), unit_id TEXT, kind TEXT NOT NULL,
    instrument TEXT NOT NULL, date TEXT, effective TEXT, year INTEGER, note TEXT NOT NULL
);
CREATE TABLE statute_units (
    id TEXT PRIMARY KEY, act_id TEXT NOT NULL REFERENCES acts(id), number TEXT NOT NULL,
    title TEXT, part TEXT, chapter TEXT, text TEXT NOT NULL, footnotes TEXT NOT NULL,
    omitted INTEGER NOT NULL
);
CREATE TABLE judgments (
    id TEXT PRIMARY KEY, site_id INTEGER UNIQUE NOT NULL, title TEXT, petitioner TEXT,
    respondent TEXT, year INTEGER, decision_date TEXT, appeal_number TEXT, bench TEXT,
    outcome TEXT, summary TEXT, questions TEXT, keywords TEXT, operative_order TEXT,
    text_truncated INTEGER NOT NULL, source_url TEXT, full_text TEXT NOT NULL
);
CREATE TABLE citations (
    citation TEXT NOT NULL, key TEXT NOT NULL, judgment_id TEXT NOT NULL REFERENCES judgments(id),
    PRIMARY KEY (key, judgment_id)
);
CREATE TABLE chunks (
    rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
    source_id TEXT NOT NULL, para_from INTEGER, para_to INTEGER, text TEXT NOT NULL
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(text, content='chunks', content_rowid='rowid');
CREATE TABLE edges (
    src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL, source_field TEXT NOT NULL,
    detail TEXT, PRIMARY KEY (src, rel, dst)
);
CREATE TABLE unresolved_refs (
    judgment_id TEXT NOT NULL, field TEXT NOT NULL, raw TEXT NOT NULL
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX edges_dst ON edges(dst, rel);
CREATE INDEX chunks_source ON chunks(source_id);
"""

_JUDGE_TITLES = re.compile(
    r"\b(justice|\(retd\.?\)|\(rtd\.?\)|retd\.?|chairman|member|mr\.?|mrs\.?|ms\.?|dr\.?|"
    r"syed|hon'?ble)\b", re.IGNORECASE)


def judge_id(name: str) -> str:
    """Canonical judge node ID: titles dropped, letters only, lower case."""
    bare = _JUDGE_TITLES.sub(" ", name)
    bare = re.sub(r"[^a-z ]", " ", bare.lower())
    return "JUDGE:" + "-".join(bare.split())


@dataclass
class _Statutes:
    units: list[StatuteUnit] = field(default_factory=list)
    editions: dict[str, str] = field(default_factory=dict)
    made_by: dict[str, str] = field(default_factory=dict)
    unplaced_notes: dict[str, list[str]] = field(default_factory=dict)


def _load_statutes() -> _Statutes:
    loaded = _Statutes()
    units, editions = loaded.units, loaded.editions
    for art in parse_constitution(sources.CONSTITUTION_PDF):
        u = StatuteUnit("CONST-1973", art.number, art.title, art.chapter, art.text, art.footnotes)
        u.part = art.part  # type: ignore[attr-defined]
        units.append(u)
    editions["CONST-1973"] = "As amended up to the Twenty-Seventh Amendment (2025)"
    for src in sources.STATUTES:
        units.extend(parse_statute(src.path, src.act_id, src.header, src.noise,
                                   src.unnumbered_headings))
        editions[src.act_id] = src.edition
    for est in sources.ESTACODE_RULES:
        rules = parse_estacode(sources.ESTACODE_PDF, est.act_id, est.first_page, est.last_page)
        units.extend(rules.units)
        editions[est.act_id] = sources.ESTACODE_EDITION
        loaded.made_by[est.act_id] = rules.authority
        loaded.unplaced_notes[est.act_id] = rules.unplaced_footnotes
    return loaded


def _insert_statutes(con, loaded: _Statutes) -> None:
    replaced = {r.old: r for r in REPLACEMENTS}
    for act in ACTS:
        r = replaced.get(act.id)
        con.execute("INSERT INTO acts VALUES (?,?,?,?,?,?,?,?)",
                    (act.id, act.title, act.unit_kind, int(act.id in loaded.editions),
                     loaded.editions.get(act.id), loaded.made_by.get(act.id),
                     r.new if r else None, r.on if r else None))
    notes = [(u.act_id, u.id, n) for u in loaded.units for n in u.footnotes]
    notes += [(a, None, n) for a, ns in loaded.unplaced_notes.items() for n in ns]
    for act_id, unit_id, note in notes:
        if a := parse_amendment(note):
            con.execute("INSERT INTO amendments VALUES (?,?,?,?,?,?,?,?)",
                        (act_id, unit_id, a.kind, a.instrument, a.date, a.effective, a.year,
                         a.note))
    for u in loaded.units:
        con.execute("INSERT INTO statute_units VALUES (?,?,?,?,?,?,?,?,?)",
                    (u.id, u.act_id, u.number, u.title, getattr(u, "part", ""), u.chapter,
                     u.text, json.dumps(u.footnotes, ensure_ascii=False), int(u.omitted)))
        con.execute("INSERT INTO edges VALUES (?,?,?,?,?)",
                    (u.id, "PART_OF", u.act_id, "statute", None))


def _insert_judgments(con, judgments: list[Judgment]) -> None:
    for j in judgments:
        con.execute(
            "INSERT INTO judgments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (j.id, j.site_id, j.title, j.petitioner, j.respondent, j.year, j.decision_date,
             j.appeal_number, json.dumps(j.bench), j.outcome, j.summary,
             json.dumps(j.questions, ensure_ascii=False), json.dumps(j.keywords),
             j.operative_order, int(j.text_truncated), j.source_url, j.full_text))
        for c in j.citations:
            con.execute("INSERT OR IGNORE INTO citations VALUES (?,?,?)",
                        (c, citation_key(c), j.id))


def _edge(con, src, rel, dst, field, detail=None):
    con.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?,?,?)", (src, rel, dst, field, detail))


def _insert_links(con, judgments: list[Judgment]) -> None:
    by_site = {j.site_id: j.id for j in judgments}
    by_key = dict(con.execute("SELECT key, judgment_id FROM citations").fetchall())
    for j in judgments:
        for ref in j.law_refs:
            if ref.act_id is None:
                con.execute("INSERT INTO unresolved_refs VALUES (?,?,?)", (j.id, "laws", ref.raw))
                continue
            targets = ref.unit_ids or [ref.act_id]
            for target, sub in zip(targets, ref.subrefs or [""] * len(targets), strict=False):
                _edge(con, j.id, "APPLIES", target, "laws_json", sub or None)
            if ref.range_end:
                _edge(con, j.id, "APPLIES", ref.range_end, "laws_json", "range end")
        for p in j.precedents:
            target = by_site.get(p.site_id) or by_key.get(p.key) or f"EXT:{p.key}"
            if target == j.id:
                continue
            _edge(con, j.id, "CITES", target, "precedents_json", p.citation)
        for name in j.bench:
            _edge(con, j.id, "DECIDED_BY", judge_id(name), "bench_members", name)
        _edge(con, j.id, "HAS_OUTCOME", f"OUTCOME:{j.outcome}", "outcome")
        for k in j.keywords:
            _edge(con, j.id, "TAGGED", "KW:" + k.lower(), "keywords")


def _insert_chunks(con, judgments: list[Judgment], units: list[StatuteUnit]) -> None:
    rows = []
    for j in judgments:
        rows.extend(judgment_chunks(j.id, j.paragraphs))
    for u in units:
        if u.omitted:
            continue
        header = f"{ACTS_BY_ID[u.act_id].title}, {u.id.split(':')[1]}: {u.title}"
        rows.extend(statute_chunks(u.id, header, u.text))
    for c in rows:
        con.execute("INSERT INTO chunks (id, kind, source_id, para_from, para_to, text) "
                    "VALUES (?,?,?,?,?,?)",
                    (c.id, c.kind, c.source_id, c.para_from, c.para_to, c.text))
    con.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")


def content_hash(con) -> str:
    """Hash of every table's rows in a fixed order, so identical sources give
    an identical hash."""
    h = hashlib.sha256()
    for table, order in (("acts", "id"), ("statute_units", "id"),
                         ("amendments", "act_id, unit_id, note"), ("judgments", "id"),
                         ("citations", "key, judgment_id"), ("chunks", "id"),
                         ("edges", "src, rel, dst"), ("unresolved_refs", "judgment_id, raw")):
        for row in con.execute(f"SELECT * FROM {table} ORDER BY {order}"):
            h.update(repr(row).encode())
    return h.hexdigest()


def quality_report(con) -> str:
    q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    lines = ["# Corpus data-quality report", ""]
    digest = q("SELECT value FROM meta WHERE key = 'content_hash'")
    no_ruling = q("SELECT COUNT(*) FROM judgments WHERE text_truncated = 0 "
                  "AND operative_order = ''")
    lines.append(f"Corpus hash: `{digest}`")
    lines += ["", "## Judgments", ""]
    lines.append(f"- Judgments: {q('SELECT COUNT(*) FROM judgments')}")
    lines.append(f"- Citations (reported in): {q('SELECT COUNT(*) FROM citations')}")
    lines.append(f"- Truncated texts: {q('SELECT SUM(text_truncated) FROM judgments')}")
    lines.append(f"- Complete texts without a found ruling: {no_ruling}")
    for column, label in (("decision_date", "decision date"), ("appeal_number", "appeal number")):
        n = q(f"SELECT COUNT(*) FROM judgments WHERE {column} IS NULL")
        lines.append(f"- Missing {label}: {n}")
    outcomes = con.execute("SELECT outcome, COUNT(*) FROM judgments GROUP BY outcome").fetchall()
    lines.append("- Outcomes: " + ", ".join(f"{o} {n}" for o, n in outcomes))
    lines += ["", "## Statutes", "", "| Act | Units | Omitted | Edition |", "|---|---|---|---|"]
    for act_id, title, edition in con.execute(
            "SELECT id, title, edition FROM acts WHERE has_text=1 ORDER BY id"):
        n, om = con.execute("SELECT COUNT(*), SUM(omitted) FROM statute_units WHERE act_id=?",
                            (act_id,)).fetchone()
        lines.append(f"| {title} | {n} | {om} | {edition} |")
    dated = q("SELECT COUNT(*) FROM amendments WHERE date IS NOT NULL OR year IS NOT NULL")
    unplaced = q("SELECT COUNT(*) FROM amendments WHERE unit_id IS NULL")
    lines.append("")
    lines.append(f"- Amendments recorded from footnotes: {q('SELECT COUNT(*) FROM amendments')} "
                 f"({dated} with a date or year, "
                 f"{unplaced} not tied to a unit)")
    lines += ["", "## Links", "", "| Relation | Count |", "|---|---|"]
    for rel, n in con.execute("SELECT rel, COUNT(*) FROM edges GROUP BY rel ORDER BY rel"):
        lines.append(f"| {rel} | {n} |")
    applies = con.execute("SELECT dst FROM edges WHERE rel='APPLIES'").fetchall()
    with_text = {r[0] for r in con.execute("SELECT id FROM statute_units")}
    linked = sum(1 for (d,) in applies if d in with_text)
    lines.append("")
    lines.append(f"- Law references pointing at a unit with text: {linked} of {len(applies)}")
    missing = Counter(d.split(":")[0] for (d,) in applies if d not in with_text)
    lines.append("- References to acts or units without text: "
                 + ", ".join(f"{a} {n}" for a, n in missing.most_common()))
    cites = con.execute("SELECT dst FROM edges WHERE rel='CITES'").fetchall()
    internal = sum(1 for (d,) in cites if d.startswith("J-"))
    lines.append(f"- Precedents inside the corpus: {internal} of {len(cites)}")
    lines.append(f"- Unresolved law references: {q('SELECT COUNT(*) FROM unresolved_refs')}")
    lines += ["", "## Chunks", ""]
    for kind, n, avg in con.execute(
            "SELECT kind, COUNT(*), AVG(LENGTH(text)) FROM chunks GROUP BY kind"):
        lines.append(f"- {kind}: {n} chunks, average {avg:.0f} characters")
    return "\n".join(lines) + "\n"


def build(out: Path = DEFAULT_OUT, judgments_csv: Path = sources.CLEAN_JUDGMENTS) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    statutes = _load_statutes()
    units = statutes.units
    judgments = load_judgments(judgments_csv)
    _insert_statutes(con, statutes)
    _insert_judgments(con, judgments)
    _insert_links(con, judgments)
    _insert_chunks(con, judgments, units)
    digest = content_hash(con)
    con.execute("INSERT INTO meta VALUES ('content_hash', ?)", (digest,))
    con.commit()
    report = quality_report(con)
    con.close()
    tmp.replace(out)
    out.with_name("quality_report.md").write_text(report, encoding="utf-8")
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    digest = build(args.out)
    print(f"Built {args.out} (content hash {digest[:12]})")


if __name__ == "__main__":
    main()
