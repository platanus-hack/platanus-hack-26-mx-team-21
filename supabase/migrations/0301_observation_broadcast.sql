-- Real-time observation listener: broadcast each newly-visible observation to its
-- tenant's private Realtime topic so the map web client can react live. The trigger
-- fires when an observation becomes visible to a tenant (a tenant_visible_observations
-- insert) — exactly when a pin appears on that tenant's map. See
-- docs/superpowers/specs/2026-06-21-realtime-observation-listener-design.md.

-- Trigger fn lives in `community` (already the home of the realtime confirmation channel).
create or replace function community.broadcast_observation()
returns trigger
language plpgsql
security definer
set search_path = extensions, public
as $$
declare
  v_payload jsonb;
begin
  begin
    select jsonb_build_object(
             'observation_id', o.id,
             'slug', ot.slug,
             'lat', ST_Y(o.location::geometry),
             'lng', ST_X(o.location::geometry),
             'sweep_id', o.sweep_id,
             'sweep', 'SWP-' || upper(substr(o.sweep_id::text, 1, 4)),
             'zone', coalesce(nullif(ageb.name, ''), agem.name),
             'observed_at', o.observed_at
           )
      into v_payload
      from vision.observations o
      join vision.observation_types ot on ot.id = o.observation_type_id
      left join geo.observation_geo_bindings b
        on b.observation_id = o.id
       and b.edition_id = (select id from geo.geo_editions where status = 'active')
      left join geo.geo_areas agem on agem.id = b.agem_area_id
      left join geo.geo_areas ageb on ageb.id = b.ageb_area_id
     where o.id = new.observation_id;

    if v_payload is not null then
      perform realtime.send(
        v_payload,
        'observation_inserted',
        'tenant:' || new.tenant_id::text,
        true   -- private topic
      );
    end if;
  exception when others then
    -- A Realtime hiccup must NEVER block the underlying insert.
    null;
  end;
  return new;
end;
$$;

create trigger tvo_broadcast_observation
  after insert on platform.tenant_visible_observations
  for each row execute function community.broadcast_observation();

-- Authorization for the private `tenant:<id>` topic: an authenticated user may RECEIVE
-- broadcast messages only for their own tenant's topic. realtime.send() inserts into
-- realtime.messages; the receive path is gated by this SELECT policy. Guarded so the
-- migration still applies on a DB without Supabase's realtime schema.
do $$
begin
  if exists (select 1 from information_schema.tables
             where table_schema = 'realtime' and table_name = 'messages') then
    execute 'alter table realtime.messages enable row level security';
    execute $p$
      create policy app_tenant_broadcast_receive on realtime.messages
        for select to authenticated
        using (
          realtime.messages.extension = 'broadcast'
          and realtime.topic() = 'tenant:' || public._app_tenant()::text
        )
    $p$;
  end if;
exception when duplicate_object then
  null;  -- policy already present (idempotent re-run)
end $$;
