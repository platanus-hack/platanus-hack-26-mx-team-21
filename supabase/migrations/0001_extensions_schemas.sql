create extension if not exists postgis with schema extensions;
create extension if not exists pgmq;     -- manages its own pgmq schema
create extension if not exists pg_cron;  -- manages its own cron schema
create extension if not exists pg_net;   -- exposes the net schema

create schema if not exists platform;
create schema if not exists vision;
create schema if not exists priority;
create schema if not exists geo;
create schema if not exists analysis;
