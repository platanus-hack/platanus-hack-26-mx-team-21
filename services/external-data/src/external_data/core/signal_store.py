from __future__ import annotations
import json
from typing import Protocol
from external_data.schema import Signal


class SignalStore(Protocol):
    def upsert(self, signals: list[Signal]) -> int: ...


class InMemorySignalStore:
    def __init__(self):
        self.rows: dict[str, Signal] = {}

    def upsert(self, signals: list[Signal]) -> int:
        for s in signals:
            self.rows[s.signal_id] = s          # deterministic id => idempotent
        return len(signals)


class PgSignalStore:
    """Upserts normalized signals into priority.external_signals. Requires migration
    0101 applied. Not unit-tested (no local Postgres); exercised against the remote
    once DB_URL is configured."""

    def __init__(self, dsn: str):
        import psycopg
        self._psycopg = psycopg
        self.dsn = dsn

    def upsert(self, signals: list[Signal]) -> int:
        if not signals:
            return 0
        sql = """
        insert into priority.external_signals
          (signal_id, source_id, risk_dimension, event_type, event_subtype, geom,
           geom_quality, occurred_at, reported_at, severity_weight, geocode_confidence,
           attributes, source_object_ref, source_url, license, fetched_at)
        values (%s,%s,%s,%s,%s,
                ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict (signal_id) do update set
          occurred_at = excluded.occurred_at,
          severity_weight = excluded.severity_weight,
          attributes = excluded.attributes,
          fetched_at = excluded.fetched_at,
          ingested_at = now()
        """
        with self._psycopg.connect(self.dsn) as c:
            with c.cursor() as cur:
                cur.executemany(sql, [(
                    s.signal_id, s.source_id, s.risk_dimension, s.event_type, s.event_subtype,
                    s.lon, s.lat, s.geom_quality, s.occurred_at, s.reported_at,
                    s.severity_weight, s.geocode_confidence, json.dumps(s.attributes),
                    s.source_object_ref, s.source_url, s.license, s.fetched_at,
                ) for s in signals])
            c.commit()
        return len(signals)
