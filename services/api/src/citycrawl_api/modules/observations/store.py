"""Writes a citizen report into the vision schema as a first-class observation, in one
transaction:

  source('whatsapp-citizen') -> sweep (point buffer) -> observation -> thumbnail row
  -> outbox event -> rebuild the tenant's visible set so it shows on the map.

Ingest is idempotent on the controller-supplied kapso_message_id (vision.citizen_report_ingest,
migration 0302): a retry with the same message id returns the already-created observation and
skips the R2 write + all inserts. Every other table already exists (migrations 0003/0004/0009/
0011). Migration 0302 MUST be applied to the live DB before this code is deployed.

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

    def lookup_by_message_id(self, kapso_message_id: str) -> str | None:
        """Return the observation id already ingested for this kapso_message_id, or None.

        Cheap pre-check the router calls BEFORE uploading bytes to R2, so a controller retry
        with the same message id does not re-upload the photo. Empty/blank message ids never
        dedupe (the controller may omit it), so they always fall through to a fresh insert.
        """
        if not kapso_message_id:
            return None
        with self._psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "select observation_id from vision.citizen_report_ingest "
                    "where kapso_message_id = %s",
                    (kapso_message_id,),
                )
                row = cur.fetchone()
        return str(row[0]) if row else None

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
        kapso_message_id: str = "",
    ) -> dict:
        with self._psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("set search_path = extensions, public")

                # 0. Idempotency: if this kapso_message_id was already ingested, return the
                #    existing observation in the SAME transaction and skip every insert. The
                #    router already skipped the R2 write via lookup_by_message_id; this is the
                #    authoritative in-transaction check that also closes the concurrent-retry
                #    window (two requests racing past the router pre-check).
                if kapso_message_id:
                    cur.execute(
                        "select observation_id from vision.citizen_report_ingest "
                        "where kapso_message_id = %s",
                        (kapso_message_id,),
                    )
                    existing = cur.fetchone()
                    if existing:
                        return {
                            "observation_id": str(existing[0]),
                            "in_boundary": False,
                            "thumbnail_path": thumbnail_path,
                            "deduped": True,
                        }

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

                # 8. Make it appear on the map — INCREMENTALLY. Clip only THIS point
                #    against EVERY active boundary and insert a visible-set row for each
                #    tenant whose boundary contains the point. (The old code pre-picked a
                #    single active tenant via `limit 1` — non-deterministic with >1 tenant
                #    and wrong for overlapping coverage. Letting the spatial test choose the
                #    tenants is correct and still O(active boundaries), not O(observations);
                #    the old `platform.rebuild_tenant_visible` re-clipped every observation
                #    on each insert — ~90s and worker-blocking once the set grew to ~180k.)
                cur.execute(
                    """
                    insert into platform.tenant_visible_observations
                        (tenant_id, boundary_version_id, observation_id, data_version)
                    select b.tenant_id, b.id, %s,
                           coalesce((select data_version from vision.read_model_state), 0)
                      from geo.tenant_boundary_versions b
                     where b.status = 'active'
                       and ST_Contains(
                             b.materialized_geometry,
                             ST_SetSRID(ST_MakePoint(%s, %s), 4326))
                    on conflict (tenant_id, observation_id) do nothing
                    returning observation_id
                    """,
                    (observation_id, lng, lat),
                )
                in_boundary = cur.fetchone() is not None

                # 9. Record the idempotency key so a later retry with the same message id
                #    dedupes (see step 0). Lost-race safe: on conflict do nothing, then
                #    re-read — if another concurrent request inserted first, return its
                #    observation id as a dedupe and roll back our (now-orphan) inserts.
                if kapso_message_id:
                    cur.execute(
                        """
                        insert into vision.citizen_report_ingest
                            (kapso_message_id, observation_id)
                        values (%s, %s)
                        on conflict (kapso_message_id) do nothing
                        returning observation_id
                        """,
                        (kapso_message_id, observation_id),
                    )
                    if cur.fetchone() is None:
                        # We lost the race: another request already ingested this message id.
                        # Discard our inserts and return the winner's observation as deduped.
                        cur.execute(
                            "select observation_id from vision.citizen_report_ingest "
                            "where kapso_message_id = %s",
                            (kapso_message_id,),
                        )
                        winner = cur.fetchone()
                        conn.rollback()
                        return {
                            "observation_id": str(winner[0]) if winner else str(observation_id),
                            "in_boundary": False,
                            "thumbnail_path": thumbnail_path,
                            "deduped": True,
                        }
            conn.commit()

        return {
            "observation_id": str(observation_id),
            "in_boundary": in_boundary,
            "thumbnail_path": thumbnail_path,
            "deduped": False,
        }
