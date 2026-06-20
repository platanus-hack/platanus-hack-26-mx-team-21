-- ROI generations and ROI polygons with risk semantics + supersession lifecycle.
-- The product of the external-data pipeline. Depends on schema `priority` (0001).
create table priority.roi_runs (
    id            uuid primary key default gen_random_uuid(),
    dimensions    text[] not null,
    params        jsonb  not null default '{}'::jsonb,
    signal_window tstzrange,
    started_at    timestamptz not null default now(),
    completed_at  timestamptz,
    roi_count     int
);

create table priority.rois (
    id               uuid primary key default gen_random_uuid(),
    run_id           uuid not null references priority.roi_runs(id),
    risk_dimension   text not null
        check (risk_dimension in ('crash','violation','flooding','road_surface','crime')),
    geom             geography(Polygon,4326) not null,
    centroid         geography(Point,4326)   not null,
    area_m2          real not null,
    risk_score       real not null,
    signal_count     int  not null,
    dominant_type    text not null,
    risk_breakdown   jsonb not null default '{}'::jsonb,
    occurred_from    timestamptz,
    occurred_to      timestamptz,
    recency_score    real,
    description      text not null,
    contributing_signal_ids text[] not null default '{}',
    source_object_refs      text[] not null default '{}',
    valid_from       timestamptz not null default now(),
    valid_to         timestamptz,
    superseded_by_run_id uuid references priority.roi_runs(id),
    created_at       timestamptz not null default now()
);
create index rois_current_gix on priority.rois using gist (geom) where valid_to is null;
create index rois_dim_ix      on priority.rois (risk_dimension)  where valid_to is null;

create view priority.current_rois as select * from priority.rois where valid_to is null;
