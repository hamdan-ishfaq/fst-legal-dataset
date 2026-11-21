import time

import pytest

from fstlegal.cluster.queue import BACKGROUND, INTERACTIVE, JobFailed, JobQueue
from fstlegal.cluster.worker import Worker
from fstlegal.llm.client import Completion


class SlowChat:
    """A model server that takes ``delay`` seconds per call and echoes the prompt."""

    def __init__(self, delay=0.0, fail=False):
        self.delay, self.fail = delay, fail

    def complete(self, messages, json_schema=None):
        time.sleep(self.delay)
        if self.fail:
            raise ConnectionError("server down")
        return Completion(messages[-1]["content"].upper(), 10, 2, self.delay)


def chat(text):
    return {"messages": [{"role": "user", "content": text}]}


def test_interactive_jobs_go_first():
    q = JobQueue()
    q.submit("bg", [chat("later")], priority=BACKGROUND)
    q.submit("run", [chat("now")], priority=INTERACTIVE)
    assert q.claim("w1").payload == chat("now")


def test_expired_lease_is_requeued_and_late_result_refused():
    q = JobQueue(lease_seconds=0.05)
    [job_id] = q.submit("run", [chat("x")])
    assert q.claim("w1").id == job_id
    time.sleep(0.1)  # w1 went silent
    job = q.claim("w2")
    assert job.id == job_id and job.attempts == 2
    assert not q.complete(job_id, "w1", {"text": "late"})
    assert q.complete(job_id, "w2", {"text": "ok"})
    assert q.wait([job_id], 1) == [{"text": "ok"}]


def test_heartbeat_keeps_the_lease():
    q = JobQueue(lease_seconds=0.1)
    [job_id] = q.submit("run", [chat("x")])
    q.claim("w1")
    for _ in range(3):
        time.sleep(0.05)
        assert q.heartbeat(job_id, "w1")
    assert q.claim("w2") is None


def test_job_fails_after_max_attempts():
    q = JobQueue(max_attempts=2)
    [job_id] = q.submit("run", [chat("x")])
    w = Worker(q, SlowChat(fail=True), "w1")
    assert w.run_once() and w.run_once() and not w.run_once()
    with pytest.raises(JobFailed, match="server down"):
        q.wait([job_id], 1)


def test_wait_times_out():
    q = JobQueue()
    with pytest.raises(TimeoutError):
        q.wait(q.submit("run", [chat("x")]), 0.1)


def test_batch_is_shared_across_workers():
    q = JobQueue()
    workers = [Worker(q, SlowChat(delay=0.3), f"w{i}").start() for i in range(2)]
    try:
        start = time.perf_counter()
        ids = q.submit("run", [chat(t) for t in "abcd"])
        results = q.wait(ids, 5)
        elapsed = time.perf_counter() - start
    finally:
        for w in workers:
            w.stop()
    assert [r["text"] for r in results] == ["A", "B", "C", "D"]  # order kept
    assert all(w.done == 2 for w in workers)
    assert elapsed < 1.0  # two at a time, not four in a row (1.2 s)
