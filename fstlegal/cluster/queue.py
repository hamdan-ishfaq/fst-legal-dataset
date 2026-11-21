"""Job queue for model calls (SDS 3.7, D-005).

Jobs live in SQLite. A worker claims the highest-priority queued job and holds
a lease on it; heartbeats extend the lease. If the lease runs out (the worker
crashed or its laptop left the network) the job goes back to the queue. After
``max_attempts`` failures the job is marked ``failed`` and the waiting run is
told. The same calls serve the hub's own worker now and remote workers later.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

INTERACTIVE, BACKGROUND = 10, 0  # priorities: lawyer waiting vs reminder research

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    priority INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'leased', 'done', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_expires REAL,
    result TEXT,
    error TEXT,
    created REAL NOT NULL,
    started REAL,
    finished REAL
);
CREATE INDEX IF NOT EXISTS jobs_ready ON jobs (state, priority DESC, created);
"""


class JobFailed(RuntimeError):
    pass


@dataclass
class Job:
    id: str
    run_id: str
    kind: str
    payload: dict
    attempts: int


class JobQueue:
    def __init__(self, path: str | Path = ":memory:", lease_seconds: float = 120,
                 max_attempts: int = 3):
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self._lock = threading.Lock()  # one connection shared by the hub's threads
        self.con = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(_SCHEMA)

    def submit(self, run_id: str, payloads: list[dict], kind: str = "chat",
               priority: int = INTERACTIVE) -> list[str]:
        """Queue several jobs at once, so free workers can take them in parallel."""
        now = time.time()
        ids = [uuid.uuid4().hex for _ in payloads]
        with self._lock:
            self.con.executemany(
                "INSERT INTO jobs (id, run_id, kind, payload, priority, state, created) "
                "VALUES (?, ?, ?, ?, ?, 'queued', ?)",
                [(i, run_id, kind, json.dumps(p), priority, now)
                 for i, p in zip(ids, payloads, strict=True)])
        return ids

    def _expire(self, now: float) -> None:
        self.con.execute(
            "UPDATE jobs SET state = CASE WHEN attempts >= ? THEN 'failed' ELSE 'queued' END, "
            "error = CASE WHEN attempts >= ? THEN 'lease expired' ELSE error END, "
            "lease_owner = NULL, lease_expires = NULL "
            "WHERE state = 'leased' AND lease_expires < ?",
            (self.max_attempts, self.max_attempts, now))

    def claim(self, worker: str) -> Job | None:
        """Lease the next job, or return None when nothing is waiting."""
        now = time.time()
        with self._lock:
            self.con.execute("BEGIN IMMEDIATE")
            try:
                self._expire(now)
                row = self.con.execute(
                    "SELECT * FROM jobs WHERE state = 'queued' "
                    "ORDER BY priority DESC, created LIMIT 1").fetchone()
                if row:
                    self.con.execute(
                        "UPDATE jobs SET state = 'leased', lease_owner = ?, lease_expires = ?, "
                        "attempts = attempts + 1, started = ? WHERE id = ?",
                        (worker, now + self.lease_seconds, now, row["id"]))
                self.con.execute("COMMIT")
            except BaseException:
                self.con.execute("ROLLBACK")
                raise
        if not row:
            return None
        return Job(row["id"], row["run_id"], row["kind"], json.loads(row["payload"]),
                   row["attempts"] + 1)

    def _update_leased(self, sql: str, params: tuple, job_id: str, worker: str) -> bool:
        """Apply an update only while ``worker`` still holds the lease."""
        with self._lock:
            cur = self.con.execute(
                f"{sql} WHERE id = ? AND state = 'leased' AND lease_owner = ?",
                (*params, job_id, worker))
        return cur.rowcount == 1

    def heartbeat(self, job_id: str, worker: str) -> bool:
        return self._update_leased("UPDATE jobs SET lease_expires = ?",
                                   (time.time() + self.lease_seconds,), job_id, worker)

    def complete(self, job_id: str, worker: str, result: dict) -> bool:
        """Store a result. False if the lease was lost and the job given to another worker."""
        return self._update_leased(
            "UPDATE jobs SET state = 'done', result = ?, finished = ?, lease_owner = ?",
            (json.dumps(result), time.time(), worker), job_id, worker)

    def fail(self, job_id: str, worker: str, error: str) -> bool:
        return self._update_leased(
            "UPDATE jobs SET state = CASE WHEN attempts >= ? THEN 'failed' ELSE 'queued' END, "
            "error = ?, lease_owner = NULL, lease_expires = NULL",
            (self.max_attempts, error), job_id, worker)

    def wait(self, job_ids: list[str], timeout: float, poll: float = 0.05) -> list[dict]:
        """Results in the order of ``job_ids``. Raises if any job failed or time ran out."""
        if not job_ids:
            return []
        deadline = time.time() + timeout
        marks = ",".join("?" * len(job_ids))
        while True:
            with self._lock:
                self._expire(time.time())
                rows = {r["id"]: r for r in self.con.execute(
                    f"SELECT id, state, result, error FROM jobs WHERE id IN ({marks})", job_ids)}
            failed = [r for r in rows.values() if r["state"] == "failed"]
            if failed:
                raise JobFailed(f"job {failed[0]['id']} failed: {failed[0]['error']}")
            if all(rows[i]["state"] == "done" for i in job_ids):
                return [json.loads(rows[i]["result"]) for i in job_ids]
            if time.time() > deadline:
                raise TimeoutError(f"{len(job_ids)} job(s) not done in {timeout:.0f}s")
            time.sleep(poll)

    def worker_of(self, job_id: str) -> str | None:
        with self._lock:
            row = self.con.execute("SELECT lease_owner FROM jobs WHERE id = ?",
                                   (job_id,)).fetchone()
        return row["lease_owner"] if row else None
