"""Brief quality on the live model, for the baseline or the RLM pipeline.

For each judgment, its first legal question is answered with that judgment
hidden. Recorded per run: claims kept and removed, citations that did not
match a retrieved source, how many of the provisions the real tribunal applied
appear among the cited statute sources, tokens and time.

Run (with ``python scripts/serve.py chat`` running):
``python -m fstlegal.eval.baseline_check --out docs/reports/baseline_verification.json``
``python -m fstlegal.eval.baseline_check --pipeline rlm --out docs/reports/rlm_verification.json``

With ``--long``, each question comes with a long case file: the hidden judgment's
own text up to its order (facts, arguments, reasoning; the result cut off), for
judgments where that runs to at least ``LONG_CHARS`` characters. This is more
than the baseline's single call can hold, which is the case the RLM is for (H1).
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
from ..rlm.engine import local_rlm

LONG_CHARS = 15_000


def case_file(judgment: dict) -> str:
    """The judgment's text before its order, or "" if the order cannot be located."""
    order = judgment["operative_order"]
    if not order or judgment["text_truncated"]:
        return ""
    start = judgment["full_text"].find(order[:60])
    return judgment["full_text"][:start] if start > 0 else ""


def run(limit: int | None, server: str, pipeline: str = "baseline", long: bool = False) -> dict:
    corpus = Corpus()
    graph = CorpusGraph(corpus)
    retriever = Retriever(corpus, graph)
    llm = ChatClient(server)
    rlm, pool = local_rlm(server) if pipeline == "rlm" else (None, [])
    rows = []
    ids = corpus.judgment_ids()
    if long:
        ids = [j for j in ids if len(case_file(corpus.judgment(j))) >= LONG_CHARS]
    for jid in ids[:limit]:
        question = corpus.judgment(jid)["questions"][0]
        papers = case_file(corpus.judgment(jid)) if long else ""
        gold = {u for u in graph.provisions_applied(jid) if u in graph.units_with_text}
        start = time.perf_counter()
        extra = {}
        if rlm:
            result = rlm.run(question, {"case_file": papers} if papers else None,
                             exclude={jid})
            brief = result.brief
            extra = {"status": result.status, "reason": result.reason, "turns": result.turns,
                     "subcalls": result.subcalls, "tokens": result.tokens}
        else:
            try:
                brief = answer(question, corpus, retriever, llm, papers, exclude={jid})
            except json.JSONDecodeError:  # the window filled up before the JSON closed
                brief = None
            call = llm.log[-1]
            extra = {"tokens": call["prompt_tokens"] + call["completion_tokens"]}
            if brief is None:
                extra["reason"] = "answer cut off at the context limit"
        seconds = time.perf_counter() - start
        if brief is None:
            rows.append({"judgment": jid, "question": question, "claims_kept": 0,
                         "claims_removed": 0, "invalid_citations": 0,
                         "all_citations_exist": True, "gold_provisions": 0,
                         "gold_provisions_cited": 0, "seconds": round(seconds, 1), **extra})
            print(f"{jid}: no answer ({extra.get('reason')}), {seconds:.0f}s", flush=True)
            continue
        kept = [c for s in SECTIONS for c in brief.sections[s]]
        cited = {brief.sources[label].ref_id for c in kept for label in c["sources"]}
        exists = all(ref.startswith("paper:") or ref in corpus.unit_ids() or corpus.judgment(ref)
                     for ref in cited)
        rows.append({
            "judgment": jid, "question": question, "claims_kept": len(kept),
            "claims_removed": len(brief.dropped_claims),
            "invalid_citations": len(brief.invalid_citations),
            "all_citations_exist": exists,
            "gold_provisions": len(gold),
            "gold_provisions_cited": len(gold & cited),
            "seconds": round(seconds, 1), **extra,
        })
        print(f"{jid}: kept {len(kept)}, removed {len(brief.dropped_claims)}, "
              f"{seconds:.0f}s", flush=True)
    for w in pool:
        w.stop()
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
        "mean_tokens": mean(r["tokens"] for r in rows),
    }
    if rlm:
        summary |= {"completed": sum(r["status"] == "complete" for r in rows),
                    "mean_turns": mean(r["turns"] for r in rows),
                    "mean_subcalls": mean(r["subcalls"] for r in rows)}
    return {"pipeline": pipeline, "long_case_files": long, "corpus_hash": corpus.content_hash,
            "summary": summary, "runs": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--pipeline", choices=("baseline", "rlm"), default="baseline")
    parser.add_argument("--long", action="store_true", help="add a long case file to each question")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = run(args.limit, args.server, args.pipeline, args.long)
    print(json.dumps(result["summary"], indent=2))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
