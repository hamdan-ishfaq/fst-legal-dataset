"""Combining keyword, dense and graph retrieval.

``Retriever`` is the retrieval API every later stage uses. Its ``mode`` picks
which signals are used, so the evaluation can compare them on equal terms.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .dense import HttpEmbedder, VectorIndex
from .graph import CorpusGraph
from .lexical import bm25_search
from .store import ChunkHit, Corpus

RRF_K = 60  # standard reciprocal-rank-fusion constant
MODES = ("bm25", "dense", "hybrid", "hybrid+graph", "bm25+graph")


def rrf(rankings: list[list[str]], weights: list[float] | None = None) -> list[tuple[str, float]]:
    """Reciprocal rank fusion of several ranked ID lists."""
    weights = weights or [1.0] * len(rankings)
    scores: dict[str, float] = defaultdict(float)
    for ranking, w in zip(rankings, weights, strict=True):
        for rank, item in enumerate(ranking):
            scores[item] += w / (RRF_K + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])


def _sources(hits: list[ChunkHit]) -> list[str]:
    """Distinct source IDs in rank order."""
    return list(dict.fromkeys(h.source_id for h in hits))


@dataclass
class Ranked:
    id: str
    score: float
    passages: list[ChunkHit]  # best matching chunks of this source, if any


class Retriever:
    def __init__(self, corpus: Corpus, graph: CorpusGraph | None = None,
                 index: VectorIndex | None = None, embedder: HttpEmbedder | None = None,
                 mode: str = "bm25+graph", depth: int = 50):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if "dense" in mode or mode.startswith("hybrid"):
            if index is None or embedder is None:
                raise ValueError(f"mode {mode!r} needs a vector index and an embedder")
        self.corpus = corpus
        self.graph = graph or CorpusGraph(corpus)
        self.index = index
        self.embedder = embedder
        self.mode = mode
        self.depth = depth

    def _text_hits(self, query: str, kind: str, exclude: set[str]) -> list[list[ChunkHit]]:
        lists = []
        if self.mode in ("bm25", "hybrid", "hybrid+graph", "bm25+graph"):
            lists.append(bm25_search(self.corpus, query, self.depth, kind, exclude))
        if self.mode in ("dense", "hybrid", "hybrid+graph"):
            qv = self.embedder.embed_query(query)
            lists.append(self.index.search(qv, self.depth, kind, exclude))
        return lists

    def _rank(self, lists: list[list[ChunkHit]], extra: list[list[str]] | None = None,
              k: int = 10) -> list[Ranked]:
        rankings = [_sources(hits) for hits in lists] + (extra or [])
        fused = rrf(rankings)
        passages: dict[str, list[ChunkHit]] = defaultdict(list)
        for hits in lists:
            for h in hits:
                if all(p.chunk_id != h.chunk_id for p in passages[h.source_id]):
                    passages[h.source_id].append(h)
        return [Ranked(i, s, passages.get(i, [])[:3]) for i, s in fused[:k]]

    def search_cases(self, query: str, k: int = 10,
                     exclude: set[str] | None = None) -> list[Ranked]:
        """Judgments relevant to the query, best first."""
        exclude = exclude or set()
        lists = self._text_hits(query, "judgment", exclude)
        extra = None
        if self.mode.endswith("+graph"):
            # judgments linked through shared provisions/precedents to the top text hits
            seeds = _sources(lists[0])[:5] if lists else []
            linked: dict[str, float] = defaultdict(float)
            for seed in seeds:
                for other, w in self.graph.related_judgments(seed, exclude):
                    linked[other] += w
            extra = [sorted(linked, key=lambda x: -linked[x])]
        return self._rank(lists, extra, k)

    def search_statutes(self, query: str, k: int = 10,
                        exclude_judgments: set[str] | None = None) -> list[Ranked]:
        """Statute units relevant to the query, best first. With graph modes,
        units applied by the most relevant judgments are fused in."""
        exclude_judgments = exclude_judgments or set()
        lists = self._text_hits(query, "statute", set())
        extra = None
        if self.mode.endswith("+graph"):
            cases = self.search_cases(query, k=10, exclude=exclude_judgments)
            weighted = [(c.id, 1 / (rank + 1)) for rank, c in enumerate(cases)]
            extra = [[u for u, _ in self.graph.provisions_from_judgments(weighted)]]
        return self._rank(lists, extra, k)
