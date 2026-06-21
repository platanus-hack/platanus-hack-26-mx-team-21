"""DatasetRefreshService — one callable that runs the full external-dataset pipeline:

    extract selected sources
      -> write raw/staged objects to object storage (R2 in production)
      -> upsert staged signals into Supabase Postgres
      -> recompute and supersede affected ROI dimensions

The HTTP router and the Typer CLI are both adapters over this service rather than separate
execution paths. `run()` is a generator yielding newline-delimited-JSON-ready progress
records so a long refresh can stream while it works. Heavy dataset libraries are imported
lazily inside run() so normal planning/LLM requests never pay for pandas/shapely/etc.

Signal upserts are idempotent (deterministic ids) and ROI supersession goes through the
existing run/store contract, so an operator can retry a partial refresh safely."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Iterator

from citycrawl_api.config import Settings
from citycrawl_api.logging import get_logger

logger = get_logger()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DatasetRefreshService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _targets(self, source_ids: list[str] | None):
        from citycrawl_api.modules.datasets.registry.loader import load_registry

        sources = load_registry()
        wanted = set(source_ids or [])
        out = []
        for s in sources:
            if not s.enabled:
                continue
            if wanted and s.id not in wanted:
                continue
            out.append(s)
        return out

    def run(
        self, source_ids: list[str] | None = None, request_id: str = "-"
    ) -> Iterator[dict]:
        """Yield progress / complete / error records. A failure after work has begun emits
        a terminal error record naming the failed stage; the caller cannot change the HTTP
        status once streaming has started."""
        # Lazy imports — keep the dataset stack out of the hot path of other routes.
        from citycrawl_api.modules.datasets.adapters import ckan_csv
        from citycrawl_api.modules.datasets.adapters.base import ExtractContext
        from citycrawl_api.modules.datasets.core.storage import make_store
        from citycrawl_api.modules.datasets.roi.runner import compute_and_store
        from citycrawl_api.modules.datasets.roi.store import InMemoryRoiStore, PgRoiStore
        from citycrawl_api.modules.datasets.schema import RoiParams, Signal

        settings = self._settings
        now = _now()

        def err(stage: str, exc: Exception) -> dict:
            # Never serialize str(exc) to the client: it can leak the DSN/host/path or other
            # internal detail, bypassing the ApiError discipline (and the stream has already
            # started, so we can't switch to a normal HTTP error). Emit a STATIC per-stage
            # message and record the real detail server-side keyed by request id.
            logger.exception(
                "dataset_refresh_failed",
                extra={"fields": {"stage": stage, "requestId": request_id}},
            )
            return {
                "type": "error",
                "stage": stage,
                "error": {
                    "code": f"dataset_{stage}_failed",
                    "message": f"{stage} failed",
                    "requestId": request_id,
                },
            }

        try:
            store = make_store(settings)
            targets = self._targets(source_ids)
        except Exception as exc:  # configuration / registry problems before any work
            yield err("init", exc)
            return

        ctx = ExtractContext(store=store, now=now)
        all_signals: list = []

        # --- extract + stage ----------------------------------------------------
        for s in targets:
            if s.kind != "ckan_csv":
                # news_geocode and future kinds need extra collaborators; skip for now.
                yield {"type": "progress", "stage": "skip", "sourceId": s.id, "count": 0}
                continue
            try:
                sigs = ckan_csv.extract(s, ctx)
                lines = "\n".join(sig.model_dump_json() for sig in sigs)
                store.write_text(f"staging/{s.id}/signals.jsonl", lines)
            except Exception as exc:
                yield err("extract", exc)
                return
            all_signals.extend(sigs)
            yield {"type": "progress", "stage": "extract", "sourceId": s.id, "count": len(sigs)}

        # --- load into Postgres -------------------------------------------------
        signal_count = 0
        if settings.db_url:
            from citycrawl_api.modules.datasets.core.signal_store import PgSignalStore

            sig_store = PgSignalStore(settings.db_url)
        else:
            from citycrawl_api.modules.datasets.core.signal_store import InMemorySignalStore

            sig_store = InMemorySignalStore()
        # group by source so progress is per-source, mirroring the CLI
        by_source: dict[str, list] = {}
        for sig in all_signals:
            by_source.setdefault(sig.source_id, []).append(sig)
        for source_id, sigs in by_source.items():
            try:
                n = sig_store.upsert(sigs)
            except Exception as exc:
                yield err("load", exc)
                return
            signal_count += n
            yield {"type": "progress", "stage": "load", "sourceId": source_id, "count": n}

        # --- recompute + supersede affected ROI dimensions ----------------------
        by_dim: dict[str, list] = {}
        for sig in all_signals:
            by_dim.setdefault(sig.risk_dimension, []).append(sig)
        roi_store = PgRoiStore(settings.db_url) if settings.db_url else InMemoryRoiStore()
        try:
            run = compute_and_store(by_dim, roi_store, RoiParams(), now)
        except Exception as exc:
            yield err("roi", exc)
            return

        yield {
            "type": "complete",
            "signalCount": signal_count,
            "roiRunId": run.run_id,
            "roiCount": run.roi_count,
            "dimensions": run.dimensions,
        }
