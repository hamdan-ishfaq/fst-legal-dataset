"""The recursive LM loop (Implementation Plan, Phase 5; Zhang et al.).

The root model never sees the case material directly. It writes code into a
REPL holding the question and case papers, calls retrieval tools, and hands
reading and analysis to sub-calls, which go through the job queue so any free
worker can run them. The loop ends when the code sets ``answer["ready"]`` or a
budget runs out; then the answer is checked like the baseline's, except that a
claim may cite only sources the run actually retrieved.

Run (with ``python scripts/serve.py chat`` running):
``python -m fstlegal.rlm.engine "Can a second departmental appeal extend limitation?"``
"""

from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from dataclasses import dataclass, field

from ..cluster.queue import JobQueue
from ..cluster.worker import Worker
from ..llm.client import ChatClient
from ..pipeline.baseline import Brief, Source, check_citations, render, unit_citation
from ..retrieval.graph import CorpusGraph
from ..retrieval.hybrid import Retriever
from ..retrieval.store import Corpus
from ..retrieval.versions import describe, judgment_law_changes
from . import prompts
from .sandbox import Sandbox
from .tools import BudgetExceeded, LegalTools, SubCalls

_CODE = re.compile(r"```repl\s*\n(.*?)\n```", re.DOTALL)  # upstream's block format
CHARS_PER_TOKEN = 3.5  # rough, for keeping the history inside the context window
# REPL output shown back per turn, shared by its blocks. The fine-tune writes up to ~20
# blocks a turn; uncapped, their output overflowed the window and was dropped unseen.
TURN_OUTPUT_CHARS = 6000


@dataclass
class Budget:
    max_turns: int = 12
    max_subcalls: int = 40
    max_tokens: int = 120_000  # prompt + completion over the whole run, root and sub-calls
    seconds: float = 1200
    context_tokens: int = 8192  # the server's window
    turn_tokens: int = 2500  # most a root turn may write, thinking included


@dataclass
class RunResult:
    brief: Brief | None
    status: str  # "complete", "incomplete" (budget hit, partial answer) or "no_answer"
    reason: str
    turns: int
    subcalls: int
    tokens: int
    seconds: float
    trace: list[dict] = field(default_factory=list)


def _fit(messages: list[dict], limit_chars: int) -> list[dict]:
    """Drop the oldest turns (assistant + REPL output) until the history fits,
    keeping the system prompt and the question."""
    head, tail = messages[:2], messages[2:]
    while len(tail) > 1 and sum(len(m["content"]) for m in head + tail) > limit_chars:
        tail = tail[1:]
    while len(tail) > 1 and tail[0]["role"] == "assistant":
        tail = tail[1:]
    return head + tail


def _sources(corpus: Corpus, tools: LegalTools) -> list[Source]:
    sources = []
    for ref in sorted(tools.seen):
        if ref.startswith("paper:"):
            sources.append(Source(ref, ref, f"Case paper: {ref[6:]}", ""))
        elif corpus.unit(ref):
            sources.append(Source(ref, ref, unit_citation(corpus, ref), ""))
        elif (j := corpus.judgment(ref)) and ref not in tools.exclude:
            notes = [describe(corpus, c, j["decision_date"])
                     for c in judgment_law_changes(corpus, ref)]
            sources.append(Source(ref, ref, j["citations"][0], "", notes))
    return sources


def _parse_answer(content) -> dict:
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return {}
    return content if isinstance(content, dict) else {}


def _claims(raw: dict) -> dict:
    """Coerce what the model wrote into ``{section: [{"text", "sources"}]}``."""
    out = {}
    for name, items in raw.items():
        items = items if isinstance(items, list) else []
        out[name] = [{"text": str(c.get("text", "")), "sources": [str(s) for s in
                      c.get("sources", []) if isinstance(s, str)]}
                     for c in items if isinstance(c, dict)]
    return out


class RLM:
    def __init__(self, corpus: Corpus, retriever: Retriever, graph: CorpusGraph,
                 root: ChatClient, queue: JobQueue, budget: Budget | None = None):
        self.corpus, self.retriever, self.graph = corpus, retriever, graph
        self.root, self.queue = root, queue
        self.budget = budget or Budget()

    def run(self, question: str, case_papers: dict[str, str] | None = None,
            exclude: set[str] | None = None) -> RunResult:
        b, start, run_id = self.budget, time.perf_counter(), uuid.uuid4().hex
        case_papers = case_papers or {}
        tools = LegalTools(self.corpus, self.retriever, self.graph, case_papers, exclude)
        subcalls = SubCalls(self.queue, run_id, b.max_subcalls, timeout=b.seconds)
        context = tools.documents(question)
        variables = {"context": context, "question": question, "case_papers": case_papers}
        limit_chars = int((b.context_tokens - b.turn_tokens) * CHARS_PER_TOKEN)
        messages = [{"role": "system", "content": prompts.system_prompt()},
                    {"role": "user", "content": prompts.metadata_prompt(
                        question, len(context), sum(map(len, context)))}]
        trace: list[dict] = []
        root_tokens, answer, reason = 0, {"content": "", "ready": False}, ""
        self.root.max_tokens = b.turn_tokens

        def tokens() -> int:
            return root_tokens + sum(r["prompt_tokens"] + r["completion_tokens"]
                                     for r in subcalls.results)

        with Sandbox(tools.functions(subcalls), variables, timeout=b.seconds) as repl:
            turn = 0
            for turn in range(b.max_turns):
                if time.perf_counter() - start > b.seconds:
                    reason = "time budget reached"
                    break
                if tokens() > b.max_tokens:
                    reason = "token budget reached"
                    break
                prompt = _fit(messages + [{"role": "user",
                                           "content": prompts.turn_prompt(turn, b.max_turns)}],
                              limit_chars)
                out = self.root.complete(prompt)
                root_tokens += out.prompt_tokens + out.completion_tokens
                messages = prompt + [{"role": "assistant", "content": out.text}]
                step = {"turn": turn + 1, "response": out.text, "code": [],
                        "prompt_tokens": out.prompt_tokens,
                        "completion_tokens": out.completion_tokens}
                trace.append(step)
                outputs = []
                for code in _CODE.findall(out.text):
                    done_calls = len(subcalls.results)
                    r = repl.run(code)
                    step["code"].append({"code": code, "stdout": r.stdout, "stderr": r.stderr,
                                         "subcalls": subcalls.results[done_calls:]})
                    outputs.append((r.stdout + ("\n" + r.stderr if r.stderr else "")).strip()
                                   or "No output")
                    if r.answer.get("content"):
                        answer = r.answer
                    if BudgetExceeded.__name__ in r.stderr:
                        reason = "sub-call budget reached"
                    if answer.get("ready") or reason:
                        break
                if outputs:
                    share = max(300, TURN_OUTPUT_CHARS // len(outputs))
                    outputs = [o if len(o) <= share else o[:share] + "\n[... output truncated]"
                               for o in outputs]
                    head = "REPL output:" if len(outputs) == 1 else "REPL output (block {}):"
                    messages.append({"role": "user", "content": "\n\n".join(
                        f"{head.format(i + 1)}\n{o}" for i, o in enumerate(outputs))})
                if answer.get("ready") or reason:
                    break
            else:
                reason = "turn budget reached"

        raw = _claims(_parse_answer(answer.get("content")))
        brief = None
        if raw:
            brief = check_citations(raw, _sources(self.corpus, tools))
            brief.question = question
            cited = {ref for claims in brief.sections.values() for c in claims
                     for ref in c["sources"]}
            brief.sources = {k: v for k, v in brief.sources.items() if k in cited}
        status = ("complete" if answer.get("ready") and brief else
                  "incomplete" if brief else "no_answer")
        if answer.get("ready") and not brief:
            reason = "final answer was not in the brief format"
        return RunResult(brief, status, reason, turn + 1, len(subcalls.jobs), tokens(),
                         time.perf_counter() - start, trace)


def local_rlm(server: str = "http://127.0.0.1:8080", workers: int = 1,
              budget: Budget | None = None) -> tuple[RLM, list[Worker]]:
    """An RLM whose sub-calls are run by ``workers`` local workers against one
    server: the single-laptop setup. Remote workers join the same queue later."""
    corpus = Corpus()
    graph = CorpusGraph(corpus)
    queue = JobQueue()
    pool = [Worker(queue, ChatClient(server), f"local-{i + 1}").start() for i in range(workers)]
    # The root plans each turn, so it thinks first (Qwen3 thinking mode); sub-calls do not
    root = ChatClient(server, extra_body={"chat_template_kwargs": {"enable_thinking": True}})
    return RLM(corpus, Retriever(corpus, graph), graph, root, queue, budget), pool


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--trace", help="write the run trace to this JSON file")
    args = parser.parse_args()
    rlm, pool = local_rlm(args.server)
    try:
        result = rlm.run(args.question)
    finally:
        for w in pool:
            w.stop()
    print(render(result.brief) if result.brief else "No answer.")
    print(f"\n_{result.status}{': ' + result.reason if result.reason else ''}; "
          f"{result.turns} turns, {result.subcalls} sub-calls, {result.tokens} tokens, "
          f"{result.seconds:.0f}s_")
    if args.trace:
        with open(args.trace, "w", encoding="utf-8") as f:
            json.dump(result.trace, f, indent=2)


if __name__ == "__main__":
    main()
