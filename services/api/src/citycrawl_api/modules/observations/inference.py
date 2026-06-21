"""Confirmation channel client. Enqueues a photo-confirmation job on
community.inference_jobs and polls for the verdict written by the non-public inference
server. Not unit-tested for the DB path (needs Postgres); exercised against the remote
with DB_URL set. See docs/superpowers/specs/2026-06-21-whatsapp-inference-channel-design.md.
"""
from __future__ import annotations

import time
from uuid import UUID, uuid4


def is_confirmed(result: dict) -> bool:
    """True iff the inference server returned a positive confirmation verdict."""
    if result.get("status") != "done":
        return False
    response = result.get("response") or {}
    return bool(response.get("confirmed"))


class PgInferenceJobStore:
    def __init__(self, dsn: str):
        import psycopg

        self._psycopg = psycopg
        self.dsn = dsn

    def enqueue(self, *, observation_id: UUID, r2_url: str, thinking_mode: str) -> UUID:
        job_id = uuid4()
        with self._psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into community.inference_jobs
                        (id, r2_url, thinking_mode, status, observation_id)
                    values (%s, %s, %s, 'pending', %s)
                    """,
                    (job_id, r2_url, thinking_mode, observation_id),
                )
        return job_id

    def wait_for_result(
        self, job_id: UUID, *, timeout_s: float, poll_interval_s: float
    ) -> dict:
        """Polls the job row until it reaches a terminal state or the timeout elapses.
        Returns {"status": 'done'|'error'|'timeout', "response": dict|None, "error": str|None}.
        Blocking — callers in async handlers must run this via asyncio.to_thread."""
        deadline = time.monotonic() + timeout_s
        # Reuse ONE connection for the whole poll loop instead of opening/closing a fresh
        # psycopg connection every iteration (~60 connect/teardown cycles per request at the
        # default 1s interval / 60s timeout). autocommit so each SELECT sees committed writes
        # from the inference server (otherwise a long-lived read transaction would snapshot
        # the 'pending' row and never observe the verdict).
        with self._psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                while True:
                    cur.execute(
                        "select status, response, error "
                        "from community.inference_jobs where id = %s",
                        (job_id,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        return {"status": "error", "response": None, "error": "job not found"}
                    status, response, error = row
                    if status in ("done", "error"):
                        return {"status": status, "response": response, "error": error}
                    if time.monotonic() >= deadline:
                        return {"status": "timeout", "response": None, "error": "inference timeout"}
                    time.sleep(poll_interval_s)
