"""Writes a citizen report into the vision schema as a first-class observation, in one
transaction:

  source('whatsapp-citizen') -> sweep (point buffer) -> observation -> thumbnail row
  -> outbox event -> rebuild the tenant's visible set so it shows on the map.

No migration is required: every table already exists (migrations 0003/0004/0009/0011).
PostGIS lives in the `extensions` schema, so we set search_path before the spatial inserts.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from citycrawl_api.errors import ApiError

# Radius (metres) of the synthetic sweep coverage around the reported point. A citizen
# report is a single point; the buffer gives resolution/coverage logic something to work with.
SWEEP_COVERAGE_RADIUS_M = 30


class PgObservationStore:
    """Not unit-tested (no local Postgres); exercised against the remote once DB_URL is set."""

    def __init__(self, dsn: str):
        import psycopg

        self._psycopg = psycopg
        self.dsn = dsn

    def create_citizen_observation(
        self,
        *,
        observation_id: UUID,
        observation_type: str,
        lat: float,
        lng: float,
        observed_at: datetime,
        reporter_wa_id: str,
        caption: str | None,
        thumbnail_bucket: str,
        thumbnail_path: str,
    ) -> dict:
        with self._psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("set search_path = extensions, public")

                # 1. Resolve the observation type.
                cur.execute(
                    "select id from vision.observation_types where slug = %s and status = 'active'",
                    (observation_type,),
                )
                row = cur.fetchone()
                if not row:
                    raise ApiError(
                        400, "unknown_observation_type",
                        f"Unknown observation type '{observation_type}'",
                    )
                type_id = row[0]

                # 2. Active tenant (the one with an active boundary) — for map visibility.
                cur.execute(
                    "select tenant_id from geo.tenant_boundary_versions where status = 'active' limit 1"
                )
                trow = cur.fetchone()
                tenant_id = trow[0] if trow else None

                # 3. Provenance source (idempotent on slug).
                cur.execute(
                    """
                    insert into vision.sources (slug, name, status)
                    values ('whatsapp-citizen', 'WhatsApp Citizen Reports', 'active')
                    on conflict (slug) do update set name = excluded.name
                    returning id
                    """
                )
                source_id = cur.fetchone()[0]

                # 4. Synthetic sweep: coverage = a small buffer around the reported point.
                cur.execute(
                    """
                    insert into vision.sweeps (source_id, coverage, started_at, ended_at)
                    values (
                        %s,
                        ST_Buffer(ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s),
                        %s, %s
                    )
                    returning id
                    """,
                    (source_id, lng, lat, SWEEP_COVERAGE_RADIUS_M, observed_at, observed_at),
                )
                sweep_id = cur.fetchone()[0]
                cur.execute(
                    """
                    insert into vision.sweep_assessed_types (sweep_id, observation_type_id)
                    values (%s, %s) on conflict do nothing
                    """,
                    (sweep_id, type_id),
                )

                # 5. The observation (immutable fact).
                cur.execute(
                    """
                    insert into vision.observations
                        (id, observation_type_id, location, observed_at, sweep_id,
                         detector_name, detector_version, detected_at, valid_from)
                    values (
                        %s, %s,
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        %s, %s, 'whatsapp-citizen', '1', now(), %s
                    )
                    """,
                    (observation_id, type_id, lng, lat, observed_at, sweep_id, observed_at),
                )

                # 6. Thumbnail pointer (the citizen photo IS the evidence).
                cur.execute(
                    """
                    insert into vision.observation_thumbnails
                        (observation_id, storage_bucket, storage_path, status)
                    values (%s, %s, %s, 'ready')
                    """,
                    (observation_id, thumbnail_bucket, thumbnail_path),
                )

                # 7. Outbox event for downstream consumers (priority, cache, thumbnails).
                cur.execute(
                    """
                    insert into vision.vision_outbox_events (event_kind, entity_id, occurred_at)
                    values ('observation_inserted', %s, now())
                    """,
                    (observation_id,),
                )

                # 8. Make it appear on the map (full rebuild; fine at this scale).
                in_boundary = False
                if tenant_id is not None:
                    cur.execute("select platform.rebuild_tenant_visible(%s)", (tenant_id,))
                    cur.execute(
                        """
                        select exists(
                            select 1 from platform.tenant_visible_observations
                            where tenant_id = %s and observation_id = %s
                        )
                        """,
                        (tenant_id, observation_id),
                    )
                    in_boundary = bool(cur.fetchone()[0])
            conn.commit()

        return {
            "observation_id": str(observation_id),
            "in_boundary": in_boundary,
            "thumbnail_path": thumbnail_path,
        }
