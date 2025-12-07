State: SoT v4.10 (current; details may lag ARCHITECTURE).
# PROJECTOR

## Purpose
- Render-only mirror of selected `objects.payload` fields to the file system.
- Never mutates DB; one-way projection for human-readable artifacts.

## Whitelist
- Core-6: id, type, title, created, updated, origin
- Optional: summary, tags, links

## Layout
- content/<type>/<id>/index.md
- assets/<id>/*

## Idempotency
- Projection re-runs safely; only writes if content changes.

## Triggers
- On `curation.review.done` and manual requests.
