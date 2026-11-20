"""Baseline implementation verification on the live model.

For each judgment, its first legal question is answered with that judgment
hidden. Recorded per run: claims kept and removed, citations that did not
match a retrieved source, how many of the provisions the real tribunal applied
appear among the cited statute sources, tokens and time.

Run (with ``python scripts/serve.py chat`` running):
``python -m fstlegal.eval.baseline_check --out docs/reports/baseline_verification.json``
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from statistics import mean

from ..llm.client import ChatClient
from ..pipeline.baseline import SECTIONS, answer
from ..retrieval.graph import CorpusGraph
from ..retrieval.hybrid import Retriever
from ..retrieval.store import Corpus


def run(limit: int | None, server: str) -> dict:
    corpus = Corpus()
    graph = CorpusGraph(corpus)
    retriever = Retriever(corpus, graph)
    llm = ChatClient(server)
    rows = []
    for jid in corpus.judgment_ids()[:limit]:
        question = corpus.judgment(jid)["questions"][0]
        gold = {u for u in graph.provisions_applied(jid) if u in graph.units_with_text}
        start = time.perf_counter()
        brief = answer(question, corpus, retriever, llm, exclude={jid})
        seconds = time.perf_counter() - start
        kept = [c for s in SECTIONS for c in brief.sections[s]]
        cited = {brief.sources[label].ref_id for c in kept for label in c["sources"]}
        exists = all(ref in corpus.unit_ids() or corpus.judgment(ref) for ref in cited)
        call = llm.log[-1]
        rows.append({
            "judgment": jid, "question": question, "claims_kept": len(kept),
            "claims_removed": len(brief.dropped_claims),
            "invalid_citations": len(brief.invalid_citations),
            "all_citations_exist": exists,
            "gold_provisions": len(gold),
            "gold_provisions_cited": len(gold & cited),
            "prompt_tokens": call["prompt_tokens"], "completion_tokens": call["completion_tokens"],
            "seconds": round(seconds, 1),
        })
        print(f"{jid}: kept {len(kept)}, removed {len(brief.dropped_claims)}, "
              f"{seconds:.0f}s", flush=True)
    with_gold = [r for r in rows if r["gold_provisions"]]
    summary = {
        "runs": len(rows),
        "citation_existence_rate": mean(r["all_citations_exist"] for r in rows),
        "mean_claims_kept": mean(r["claims_kept"] for r in rows),
        "share_of_claims_removed": sum(r["claims_removed"] for r in rows)
        / max(1, sum(r["claims_kept"] + r["claims_removed"] for r in rows)),
        "gold_provision_recall": (sum(r["gold_provisions_cited"] for r in with_gold)
                                  / max(1, sum(r["gold_provisions"] for r in with_gold))),
        "mean_seconds": mean(r["seconds"] for r in rows),
        "mean_completion_tokens": mean(r["completion_tokens"] for r in rows),
    }
    return {"corpus_hash": corpus.content_hash, "summary": summary, "runs": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = run(args.limit, args.server)
    print(json.dumps(result["summary"], indent=2))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
