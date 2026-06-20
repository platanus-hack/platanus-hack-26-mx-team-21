-- ---- RLS ----
alter table platform.tenant_visible_observations enable row level security;
create policy tvo_read on platform.tenant_visible_observations
    for select to authenticated
    using (tenant_id = platform.active_tenant_id() and platform.is_member(tenant_id, 'viewer'));

alter table vision.observations enable row level security;
create policy obs_read on vision.observations
    for select to authenticated
    using (exists (
        select 1 from platform.tenant_visible_observations v
        where v.observation_id = vision.observations.id
          and v.tenant_id = platform.active_tenant_id()
          and platform.is_member(v.tenant_id, 'viewer')
    ));

alter table analysis.analysis_runs enable row level security;
create policy runs_read on analysis.analysis_runs
    for select to authenticated
    using (platform.is_member(tenant_id, 'viewer'));
create policy runs_write on analysis.analysis_runs
    for insert to authenticated
    with check (platform.is_member(tenant_id, 'analysis_author'));

-- ---- Observation immutability ----
create or replace function vision.enforce_observation_immutability()
returns trigger language plpgsql as $$
begin
    if (new.observation_type_id, new.location, new.observed_at, new.sweep_id,
        new.frame_ref, new.detector_name, new.detector_version, new.detected_at,
        new.valid_from, new.created_at)
       is distinct from
       (old.observation_type_id, old.location, old.observed_at, old.sweep_id,
        old.frame_ref, old.detector_name, old.detector_version, old.detected_at,
        old.valid_from, old.created_at)
    then raise exception 'immutable observation fact/provenance column changed'; end if;

    if old.recording_id is not null and new.recording_id is distinct from old.recording_id then
        raise exception 'recording_id is set-once'; end if;
    if old.media_offset_ms is not null and new.media_offset_ms is distinct from old.media_offset_ms then
        raise exception 'media_offset_ms is set-once'; end if;
    if old.superseded_by_observation_id is not null
       and new.superseded_by_observation_id is distinct from old.superseded_by_observation_id then
        raise exception 'superseded_by is set-once'; end if;
    if old.resolved_at is not null and new.resolved_at is distinct from old.resolved_at then
        raise exception 'resolved_at is set-once'; end if;
    if old.valid_to is not null and new.valid_to is distinct from old.valid_to then
        raise exception 'valid_to is set-once'; end if;
    return new;
end $$;
create trigger observations_immutable before update on vision.observations
    for each row execute function vision.enforce_observation_immutability();

-- ---- Append-only tables ----
create or replace function platform.reject_mutation() returns trigger
language plpgsql as $$
begin raise exception 'table % is append-only', tg_table_name; end $$;

create trigger audit_events_append_only before update or delete on platform.audit_events
    for each row execute function platform.reject_mutation();
create trigger run_observations_append_only before update or delete on analysis.run_observations
    for each row execute function platform.reject_mutation();
create trigger run_observation_attributes_append_only before update or delete on analysis.run_observation_attributes
    for each row execute function platform.reject_mutation();
create trigger run_priority_values_append_only before update or delete on analysis.run_priority_values
    for each row execute function platform.reject_mutation();
create trigger obs_attr_values_append_only before update or delete on vision.observation_attribute_values
    for each row execute function platform.reject_mutation();
