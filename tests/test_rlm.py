import json

import pytest

from fstlegal.cluster.queue import JobQueue
from fstlegal.cluster.worker import Worker
from fstlegal.llm.client import Completion
from fstlegal.pipeline.baseline import SECTIONS
from fstlegal.rlm.engine import Budget, _fit
from fstlegal.rlm.sandbox import Sandbox


@pytest.fixture(scope="module")
def repl():
    tools = {"double": lambda x: x * 2, "boom": lambda: 1 / 0}
    with Sandbox(tools, {"context": "abc"}, timeout=3) as box:
        yield box


def test_variables_persist_and_tools_cross_the_process(repl):
    repl.run("n = double(len(context))")
    assert repl.run("print(n)").stdout.strip() == "6"


def test_files_and_unlisted_modules_are_blocked(repl):
    assert "not available" in repl.run("import os").stderr
    assert "NameError" in repl.run("open('corpus.db')").stderr
    assert repl.run("import json; print(json.dumps([1]))").stdout.strip() == "[1]"


def test_tool_errors_reach_the_code(repl):
    assert "ZeroDivisionError" in repl.run("boom()").stderr


def test_answer_is_reported(repl):
    r = repl.run('answer["content"] = {"a": 1}; answer["ready"] = True')
    assert r.answer == {"content": {"a": 1}, "ready": True}


def test_runaway_code_is_stopped():
    with Sandbox({}, {}, timeout=1) as box:
        r = box.run("while True: pass")
        assert r.timed_out and "restarted" in r.stderr
        assert box.run("print(1)").stdout.strip() == "1"  # usable again


def test_history_keeps_system_prompt_and_question():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
    msgs += [{"role": r, "content": "x" * 100} for r in ("user", "assistant", "user")] * 3
    fitted = _fit(msgs, 350)
    assert fitted[:2] == msgs[:2]
    assert sum(len(m["content"]) for m in fitted) <= 350
    assert fitted[2]["role"] == "user"


class ScriptedRoot:
    """A root model that replays fixed turns."""

    def __init__(self, turns):
        self.turns, self.max_tokens, self.seen = list(turns), 0, []

    def complete(self, messages, json_schema=None):
        self.seen.append(messages)
        text = self.turns.pop(0) if self.turns else "Thinking."
        return Completion(text, 100, 20, 0.0)


class EchoChat:
    def complete(self, messages, json_schema=None):
        return Completion("summary: " + messages[-1]["content"][:30], 50, 10, 0.0)


@pytest.fixture(scope="module")
def corpus_parts():
    from fstlegal.corpus.build import DEFAULT_OUT
    if not DEFAULT_OUT.exists():
        pytest.skip("corpus.db not built")
    from fstlegal.retrieval.graph import CorpusGraph
    from fstlegal.retrieval.hybrid import Retriever
    from fstlegal.retrieval.store import Corpus
    corpus = Corpus(DEFAULT_OUT)
    graph = CorpusGraph(corpus)
    return corpus, Retriever(corpus, graph), graph


def run_rlm(corpus_parts, turns, budget=None, exclude=None):
    from fstlegal.rlm.engine import RLM
    queue = JobQueue()
    worker = Worker(queue, EchoChat(), "local-1").start()
    try:
        root = ScriptedRoot(turns)
        rlm = RLM(*corpus_parts, root, queue, budget or Budget(max_turns=4))
        return rlm.run("Can a civil servant be dismissed without a regular inquiry?",
                       exclude=exclude), root
    finally:
        worker.stop()


FINAL = """```repl
claims = {s: [] for s in SECTIONS_}
claims["relevant_law"] = [{"text": "Inquiry needed", "sources": [hits[0]["id"]]},
                          {"text": "Invented", "sources": ["J-999999"]}]
answer["content"] = claims
answer["ready"] = True
```""".replace("SECTIONS_", repr(list(SECTIONS)))


@pytest.mark.data
def test_rlm_retrieves_delegates_and_answers(corpus_parts):
    turns = ["Look first.\n```repl\nhits = search_statutes(question)\n"
             "notes = llm_query_batched([h['text'] for h in hits[:2]])\n"
             "print(len(hits), notes[0][:8])\n```", FINAL]
    result, root = run_rlm(corpus_parts, turns)
    assert result.status == "complete" and result.turns == 2
    assert result.subcalls == 2
    assert "6 summary:" in root.seen[1][-2]["content"]  # REPL output fed back
    law = result.brief.sections["relevant_law"]
    assert [c["text"] for c in law] == ["Inquiry needed"]  # unretrieved source removed
    assert result.trace[0]["code"][0]["subcalls"][0]["worker"] == "local-1"


@pytest.mark.data
def test_many_blocks_in_one_turn_still_fit_the_history(corpus_parts):
    from fstlegal.rlm.engine import TURN_OUTPUT_CHARS
    turns = ["\n".join(["```repl\nprint('x' * 4000)\n```"] * 20)]
    _, root = run_rlm(corpus_parts, turns, Budget(max_turns=2))
    fed_back = root.seen[1][-2]["content"]
    assert fed_back.startswith("REPL output (block 1)")
    assert len(fed_back) < TURN_OUTPUT_CHARS + 2000


@pytest.mark.data
def test_hidden_judgment_cannot_be_read(corpus_parts):
    corpus = corpus_parts[0]
    hidden = corpus.judgment_ids()[0]
    turns = [f"```repl\nprint(get_judgment('{hidden}'))\n```"]
    result, _ = run_rlm(corpus_parts, turns, exclude={hidden})
    assert "KeyError" in result.trace[0]["code"][0]["stderr"]


@pytest.mark.data
def test_turn_budget_ends_the_run(corpus_parts):
    result, _ = run_rlm(corpus_parts, [], Budget(max_turns=2))
    assert (result.status, result.reason, result.turns) == ("no_answer", "turn budget reached", 2)


@pytest.mark.data
def test_subcall_budget_ends_the_run(corpus_parts):
    turns = ["```repl\nllm_query_batched(['a', 'b', 'c'])\n```"]
    result, _ = run_rlm(corpus_parts, turns, Budget(max_turns=4, max_subcalls=2))
    assert result.reason == "sub-call budget reached" and result.subcalls == 0


def test_answer_as_json_text_is_accepted():
    from fstlegal.rlm.engine import _claims, _parse_answer
    raw = _claims(_parse_answer(json.dumps({"checklist": [{"text": "File", "sources": ["x"]}]})))
    assert raw == {"checklist": [{"text": "File", "sources": ["x"]}]}


def test_bare_last_expression_is_shown(repl):
    assert repl.run("x = 2\nx + 1").stdout.strip() == "3"
    assert repl.run("print('a')").stdout.strip() == "a"  # None is not echoed
