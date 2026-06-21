from __future__ import annotations
import json
from typing import Protocol
from citycrawl_api.modules.datasets.schema import Roi


class RoiStore(Protocol):
    def start_run(self, dimensions: list[str], params: dict) -> str: ...
    def write_rois(self, run_id: str, rois: list[Roi]) -> None: ...
    def supersede(self, run_id: str, dimensions: list[str]) -> int: ...
    def complete_run(self, run_id: str, count: int) -> None: ...
    def current(self, dimension: str | None = None) -> list[Roi]: ...


class _Row:
    __slots__ = ("roi", "run_id", "valid")

    def __init__(self, roi: Roi, run_id: str):
        self.roi, self.run_id, self.valid = roi, run_id, True


class InMemoryRoiStore:
    def __init__(self):
        self._rows: list[_Row] = []
        self._runs = 0

    def start_run(self, dimensions: list[str], params: dict) -> str:
        self._runs += 1
        return f"run-{self._runs}"

    def write_rois(self, run_id: str, rois: list[Roi]) -> None:
        self._rows.extend(_Row(r, run_id) for r in rois)

    def supersede(self, run_id: str, dimensions: list[str]) -> int:
        n = 0
        for row in self._rows:
            if row.valid and row.run_id != run_id and row.roi.risk_dimension in dimensions:
                row.valid = False
                n += 1
        return n

    def complete_run(self, run_id: str, count: int) -> None:  # no-op in memory
        pass

    def current(self, dimension: str | None = None) -> list[Roi]:
        return [r.roi for r in self._rows
                if r.valid and (dimension is None or r.roi.risk_dimension == dimension)]

    def all_rois(self) -> list[Roi]:
        return [r.roi for r in self._rows]


class PgRoiStore:
    """psycopg implementation. Requires migrations 0101-0102 applied. Not unit-tested
    (no local Postgres); exercised by an opt-in integration test when DB_URL is set."""

    def __init__(self, dsn: str):
        import psycopg
        self._psycopg = psycopg
        self.dsn = dsn

    def start_run(self, dimensions: list[str], params: dict) -> str:
        with self._psycopg.connect(self.dsn) as c:
            row = c.execute(
                "insert into priority.roi_runs (dimensions, params) values (%s, %s) returning id",
                (dimensions, json.dumps(params)),
            ).fetchone()
            c.commit()
            return str(row[0])

    def write_rois(self, run_id: str, rois: list[Roi]) -> None:
        with self._psycopg.connect(self.dsn) as c:
            for r in rois:
                c.execute(
                    """insert into priority.rois
                       (run_id, risk_dimension, geom, centroid, area_m2, risk_score,
                        signal_count, dominant_type, risk_breakdown, occurred_from, occurred_to,
                        recency_score, description, contributing_signal_ids, source_object_refs)
                       values (%s,%s,
                         ST_SetSRID(ST_GeomFromText(%s),4326)::geography,
                         ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,
                         %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (run_id, r.risk_dimension, r.polygon_wkt, r.centroid_lon, r.centroid_lat,
                     r.area_m2, r.risk_score, r.signal_count, r.dominant_type,
                     json.dumps(r.risk_breakdown), r.occurred_from, r.occurred_to,
                     r.recency_score, r.description, r.contributing_signal_ids,
                     r.source_object_refs),
                )
            c.commit()

    def supersede(self, run_id: str, dimensions: list[str]) -> int:
        with self._psycopg.connect(self.dsn) as c:
            cur = c.execute(
                """update priority.rois set valid_to = now(), superseded_by_run_id = %s
                   where valid_to is null and run_id <> %s and risk_dimension = any(%s)""",
                (run_id, run_id, dimensions),
            )
            c.commit()
            return cur.rowcount

    def complete_run(self, run_id: str, count: int) -> None:
        with self._psycopg.connect(self.dsn) as c:
            c.execute("update priority.roi_runs set completed_at = now(), roi_count = %s where id = %s",
                      (count, run_id))
            c.commit()

    def current(self, dimension: str | None = None) -> list[Roi]:
        raise NotImplementedError("read ROIs via SQL/current_rois for serving")
