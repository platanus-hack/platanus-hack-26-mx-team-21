-- External risk signals (clustering input for ROIs). Added by the external-data
-- pipeline on top of the parallel data-model migrations (depends on schema
-- `priority` and PostGIS in `extensions` from 0001). Numbered 0101+ to avoid the
-- reserved 0003-0014 band.
create table priority.external_signals (
    signal_id          text primary key,
    source_id          text not null,
    risk_dimension     text not null
        check (risk_dimension in ('crash','violation','flooding','road_surface','crime')),
    event_type         text not null,
    event_subtype      text,
    geom               geography(Point,4326) not null,
    geom_quality       text not null check (geom_quality in ('point','geocoded','block_centroid')),
    occurred_at        timestamptz,
    reported_at        timestamptz,
    severity_weight    real not null default 1,
    geocode_confidence real,
    attributes         jsonb not null default '{}'::jsonb,
    source_object_ref  text,
    source_url         text,
    license            text,
    fetched_at         timestamptz,
    ingested_at        timestamptz not null default now()
);
create index external_signals_gix    on priority.external_signals using gist (geom);
create index external_signals_dim_ix on priority.external_signals (risk_dimension);
