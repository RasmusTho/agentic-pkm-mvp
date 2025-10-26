alter table if exists objects add column if not exists path text;
create table if not exists file_state (
  path text primary key,
  uuid text,
  fm_hash text,
  body_hash text,
  mtime timestamptz,
  last_seen timestamptz default now()
);
create index if not exists file_state_uuid_idx on file_state(uuid);
