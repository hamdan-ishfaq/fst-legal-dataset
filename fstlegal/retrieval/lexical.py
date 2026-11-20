"""BM25 keyword search over chunks with SQLite FTS5."""

from __future__ import annotations

import re

from .store import ChunkHit, Corpus

# Common English and legal-boilerplate words that only add noise to a BM25 query.
STOPWORDS = frozenset("""
a an and are as at be been being by can could did do does for from had has have he her his
if in into is it its may might must not of on or shall should such that the their them then
there these they this those to under upon was were what when where whether which while who
whom why will with would without against any being can cannot also its whose been
""".split())


def fts_query(text: str) -> str:
    """Turn free text into an FTS5 OR-query of quoted terms, so user text can
    never be read as FTS5 syntax."""
    terms = re.findall(r"[A-Za-z0-9]+", text.lower())
    kept = [t for t in dict.fromkeys(terms) if t not in STOPWORDS and len(t) > 1]
    return " OR ".join(f'"{t}"' for t in kept)


def bm25_search(corpus: Corpus, text: str, k: int = 20, kind: str | None = None,
                exclude_sources: set[str] | None = None) -> list[ChunkHit]:
    query = fts_query(text)
    if not query:
        return []
    sql = ("SELECT c.id, c.kind, c.source_id, c.text, c.para_from, c.para_to, "
           "bm25(chunks_fts) AS score FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid "
           "WHERE chunks_fts MATCH ?")
    params: list = [query]
    if kind:
        sql += " AND c.kind = ?"
        params.append(kind)
    sql += " ORDER BY score LIMIT ?"
    # fetch extra rows so excluded sources do not shrink the result below k
    params.append(k + (200 if exclude_sources else 0))
    hits = []
    for r in corpus.con.execute(sql, params):
        if exclude_sources and r["source_id"] in exclude_sources:
            continue
        # FTS5 bm25() is lower-is-better; flip it so higher is better everywhere
        hits.append(ChunkHit(r["id"], r["kind"], r["source_id"], r["text"], -r["score"],
                             r["para_from"], r["para_to"]))
        if len(hits) == k:
            break
    return hits
