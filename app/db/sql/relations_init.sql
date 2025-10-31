create table if not exists relations (
  src_uuid text not null,
  dst_uuid text not null,
  relation_type text not null,
  weight double precision not null default 1.0,
  provenance jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists relations_src_idx on relations(src_uuid);
create index if not exists relations_dst_idx on relations(dst_uuid);
create index if not exists relations_type_idx on relations(relation_type);
