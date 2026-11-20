"""Leave-one-out retrieval evaluation (gold set E1 in the implementation plan).

For each judgment, each of its legal questions is used as a query with that
judgment hidden. A retrieved statute unit counts as relevant if the hidden
judgment actually applied it. This measures whether the system finds the law a
real tribunal relied on for the same question.

Run: ``python -m fstlegal.eval.retrieval_eval --modes bm25 bm25+graph``
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from ..retrieval.graph import CorpusGraph
from ..retrieval.hybrid import MODES, Retriever
from ..retrieval.store import Corpus

KS = (1, 3, 5, 10)


@dataclass
class Query:
    judgment_id: str
    text: str
    gold: set[str]


def common_units(graph: CorpusGraph, share: float) -> set[str]:
    """Units applied by more than ``share`` of all judgments, such as the
    section giving the right of appeal. They say little about a specific case."""
    judgments = [n for n, t in graph.g.nodes(data="type") if t == "judgment"]
    return {u for u in graph.units_with_text
            if len(graph.judgments_applying(u)) > share * len(judgments)}


def build_queries(corpus: Corpus, graph: CorpusGraph,
                  ignore: set[str] | None = None) -> list[Query]:
    ignore = ignore or set()
    queries = []
    for jid in corpus.judgment_ids():
        gold = {u for u in graph.provisions_applied(jid)
                if u in graph.units_with_text and u not in ignore}
        if not gold:
            continue
        for q in corpus.judgment(jid)["questions"]:
            queries.append(Query(jid, q, gold))
    return queries


def recall_at(ranked: list[str], gold: set[str], k: int) -> float:
    return len(set(ranked[:k]) & gold) / len(gold)


def ndcg_at(ranked: list[str], gold: set[str], k: int) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, r in enumerate(ranked[:k]) if r in gold)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(gold), k)))
    return dcg / ideal


def mrr(ranked: list[str], gold: set[str]) -> float:
    return next((1 / (i + 1) for i, r in enumerate(ranked) if r in gold), 0.0)


def evaluate(retriever: Retriever, queries: list[Query]) -> dict[str, float]:
    rows = []
    for q in queries:
        ranked = [r.id for r in retriever.search_statutes(q.text, k=max(KS),
                                                          exclude_judgments={q.judgment_id})]
        row = {f"recall@{k}": recall_at(ranked, q.gold, k) for k in KS}
        row["ndcg@10"] = ndcg_at(ranked, q.gold, 10)
        row["mrr"] = mrr(ranked, q.gold)
        rows.append(row)
    return {key: mean(r[key] for r in rows) for key in rows[0]}


def evaluate_popularity(graph: CorpusGraph, queries: list[Query]) -> dict[str, float]:
    """Control: ignore the query and rank units by how many other judgments
    apply them. Graph retrieval has to beat this to show it uses the query."""
    rows = []
    for q in queries:
        counts: dict[str, int] = {}
        for unit in graph.units_with_text:
            n = sum(1 for j in graph.judgments_applying(unit) if j != q.judgment_id)
            if n:
                counts[unit] = n
        ranked = sorted(counts, key=lambda u: (-counts[u], u))
        row = {f"recall@{k}": recall_at(ranked, q.gold, k) for k in KS}
        row["ndcg@10"] = ndcg_at(ranked, q.gold, 10)
        row["mrr"] = mrr(ranked, q.gold)
        rows.append(row)
    return {key: mean(r[key] for r in rows) for key in rows[0]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modes", nargs="+", default=["bm25", "bm25+graph"], choices=MODES)
    parser.add_argument("--out", type=Path, help="write results as JSON")
    parser.add_argument("--embed-url", help="OpenAI-compatible embeddings server")
    parser.add_argument("--embed-model", default="embedding")
    parser.add_argument("--ignore-common", type=float, metavar="SHARE",
                        help="drop gold units applied by more than this share of judgments")
    args = parser.parse_args()

    corpus = Corpus()
    graph = CorpusGraph(corpus)
    ignore = common_units(graph, args.ignore_common) if args.ignore_common else set()
    queries = build_queries(corpus, graph, ignore)
    index = embedder = None
    if any("dense" in m or m.startswith("hybrid") for m in args.modes):
        from ..retrieval.dense import HttpEmbedder, VectorIndex
        embedder = HttpEmbedder(args.embed_url, args.embed_model)
        index = VectorIndex.build(corpus, embedder, corpus.path.parent)

    results = {"corpus_hash": corpus.content_hash, "queries": len(queries),
               "ignored_gold_units": sorted(ignore),
               "judgments": len({q.judgment_id for q in queries}),
               "modes": {"popularity (control)": evaluate_popularity(graph, queries)}}
    for mode in args.modes:
        r = Retriever(corpus, graph, index, embedder, mode=mode)
        results["modes"][mode] = evaluate(r, queries)

    print(f"{results['queries']} queries from {results['judgments']} judgments"
          + (f", ignoring {sorted(ignore)}" if ignore else ""))
    header = ["mode"] + list(next(iter(results["modes"].values())))
    print(" | ".join(header))
    for mode, m in results["modes"].items():
        print(" | ".join([mode] + [f"{v:.3f}" for v in m.values()]))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
