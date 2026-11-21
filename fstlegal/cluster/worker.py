"""A worker that takes model-call jobs from the queue and runs them.

The hub runs one of these against its own llama-server. Remote laptops will
run the same loop over HTTP (Phase 7); until then several local workers can
point at different servers to test parallel dispatch.
"""

from __future__ import annotations

import threading

from ..llm.client import ChatClient
from .queue import Job, JobQueue


def run_job(llm: ChatClient, job: Job) -> dict:
    p = job.payload
    if job.kind != "chat":
        raise ValueError(f"unknown job kind {job.kind!r}")
    out = llm.complete(p["messages"], p.get("json_schema"))
    return {"text": out.text, "prompt_tokens": out.prompt_tokens,
            "completion_tokens": out.completion_tokens, "seconds": out.seconds}


class Worker:
    def __init__(self, queue: JobQueue, llm: ChatClient, name: str, idle_wait: float = 0.05):
        self.queue, self.llm, self.name, self.idle_wait = queue, llm, name, idle_wait
        self.done = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> bool:
        """Run one job if any is waiting. Returns whether a job was taken."""
        job = self.queue.claim(self.name)
        if job is None:
            return False
        beat = threading.Event()

        def heartbeat() -> None:
            while not beat.wait(self.queue.lease_seconds / 3):
                self.queue.heartbeat(job.id, self.name)

        threading.Thread(target=heartbeat, daemon=True).start()
        try:
            result = run_job(self.llm, job)
        except Exception as e:  # report any failure so the job can be retried elsewhere
            self.queue.fail(job.id, self.name, f"{type(e).__name__}: {e}")
        else:
            self.queue.complete(job.id, self.name, result)
            self.done += 1
        finally:
            beat.set()
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.run_once():
                self._stop.wait(self.idle_wait)

    def start(self) -> Worker:
        self._thread = threading.Thread(target=self._loop, name=self.name, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
