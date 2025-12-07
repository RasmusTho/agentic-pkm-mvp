State: SoT v4.10 (current; details may lag ARCHITECTURE).
# Data Model (AMG/SetDB)

## objects
id uuid pk
kind text
source_ref text
ts timestamptz default now()
payload jsonb
search_vector tsvector generated

## chunks
id uuid pk
object_id uuid fk objects(id) on delete cascade
idx int
offset_start int
offset_end int
text text

## embeddings
id uuid pk
object_id uuid fk objects(id) on delete cascade
model text
dim int
vec vector

## relations
id uuid pk
src uuid
dst uuid
kind text

## sets
id uuid pk
slug text unique
kind text
title text
rules jsonb

## membership
id uuid pk
set_id uuid fk sets(id) on delete cascade
object_id uuid fk objects(id) on delete cascade
reason text
score float

## decisions
id uuid pk
object_id uuid fk objects(id) on delete cascade
key text
value jsonb
created_at timestamptz default now()

## audit
id uuid pk
object_id uuid null
agent text
action text
ts timestamptz default now()
trace_id text
details jsonb
