select pgmq.create('analysis_jobs');
select pgmq.create('materialization_jobs');
select pgmq.create('thumbnail_jobs');

-- Move undelivered outbox rows into pgmq, marking them delivered.
create or replace function platform.drain_outbox() returns void
language plpgsql security definer set search_path = '' as $$
declare r record;
begin
  for r in select id, event_kind, entity_id, related_id
           from vision.vision_outbox_events where delivery_state = 'pending'
           order by occurred_at loop
    perform pgmq.send('materialization_jobs',
      jsonb_build_object('outbox_id', r.id, 'kind', r.event_kind,
                         'entity_id', r.entity_id, 'related_id', r.related_id));
    if r.event_kind = 'observation_inserted' then
      perform pgmq.send('thumbnail_jobs', jsonb_build_object('observation_id', r.entity_id));
    end if;
    update vision.vision_outbox_events set delivery_state = 'delivered' where id = r.id;
  end loop;

  for r in select id, aggregate_id, event_kind, payload
           from analysis.analysis_outbox_events where delivery_state = 'pending'
           order by created_at loop
    perform pgmq.send('analysis_jobs',
      jsonb_build_object('outbox_id', r.id, 'kind', r.event_kind,
                         'aggregate_id', r.aggregate_id, 'payload', r.payload));
    update analysis.analysis_outbox_events set delivery_state = 'delivered' where id = r.id;
  end loop;
end $$;

select cron.schedule('drain_outbox', '10 seconds', 'select platform.drain_outbox();');
