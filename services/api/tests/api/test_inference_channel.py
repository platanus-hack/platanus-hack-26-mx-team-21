"""Unit tests for the inference-confirmation channel helpers. Pure logic only — the
PgInferenceJobStore DB path needs Postgres and is covered by the DB-guarded test below."""
import os
import uuid

import pytest

from citycrawl_api.modules.observations.inference import is_confirmed
from citycrawl_api.modules.observations.storage import object_locator


def test_object_locator_builds_s3_uri():
    assert object_locator("observation-thumbnails", "observations/x/report.jpg") == \
        "s3://observation-thumbnails/observations/x/report.jpg"


def test_is_confirmed_true_when_done_and_confirmed():
    assert is_confirmed({"status": "done", "response": {"confirmed": True}}) is True


def test_is_confirmed_false_when_not_done():
    assert is_confirmed({"status": "timeout", "response": None, "error": "x"}) is False


def test_is_confirmed_false_when_verdict_negative():
    assert is_confirmed({"status": "done", "response": {"confirmed": False}}) is False


def test_is_confirmed_false_when_response_missing():
    assert is_confirmed({"status": "done", "response": None}) is False


@pytest.mark.skipif(not os.getenv("DB_URL"), reason="needs a live Postgres (DB_URL)")
def test_enqueue_then_wait_returns_simulated_verdict():
    """Enqueue a job, simulate the inference server completing it, assert wait returns it.
    Runs only when DB_URL points at the remote (migration 0300 applied)."""
    import psycopg

    from citycrawl_api.modules.observations.inference import PgInferenceJobStore

    dsn = os.environ["DB_URL"]
    store = PgInferenceJobStore(dsn)
    obs_id = uuid.uuid4()
    job_id = store.enqueue(
        observation_id=obs_id, r2_url="s3://observation-thumbnails/t/report.jpg",
        thinking_mode="flash",
    )
    # Act as the inference server: write a positive verdict.
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "update community.inference_jobs set status='done', "
            "response='{\"confirmed\": true}'::jsonb where id = %s",
            (job_id,),
        )
    result = store.wait_for_result(job_id, timeout_s=5, poll_interval_s=0.2)
    assert result["status"] == "done"
    assert result["response"]["confirmed"] is True
    # cleanup
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("delete from community.inference_jobs where id = %s", (job_id,))
