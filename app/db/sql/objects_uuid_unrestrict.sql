alter table public.objects
  alter column uuid drop expression;

-- ensure uuid is not null going forward
alter table public.objects
  alter column uuid set not null;

-- ensure logical uniqueness on uuid
create unique index if not exists objects_uuid_unique_idx
  on public.objects(uuid);
