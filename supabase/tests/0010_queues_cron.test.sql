do $$
begin
  assert exists (select 1 from pgmq.list_queues() where queue_name = 'analysis_jobs'), 'analysis_jobs queue missing';
  assert exists (select 1 from pgmq.list_queues() where queue_name = 'materialization_jobs'), 'materialization_jobs queue missing';
  assert exists (select 1 from pgmq.list_queues() where queue_name = 'thumbnail_jobs'), 'thumbnail_jobs queue missing';
  assert to_regprocedure('platform.drain_outbox()') is not null, 'drain_outbox missing';
  assert exists (select 1 from cron.job where jobname = 'drain_outbox'), 'cron drain job missing';
end $$;
