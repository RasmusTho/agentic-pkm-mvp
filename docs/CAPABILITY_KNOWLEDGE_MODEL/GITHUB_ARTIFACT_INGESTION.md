---
name: GitHub Artifact Ingestion
description: Issues and PRs adapter via gh REST, normalized into CKM artifact records with watermarks and offline-degrade
task_id: CKM-04
source_anchor: docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 5.14 Data Sources
parent_capability: Capability Knowledge Model
prerequisites: [CKM-01]
depends_on: [CKM_STORE_AND_OBJECT_MODEL.md]
can_parallelize_with: [Capability Registry Seed, Repo Artifact Ingestion]
---

# GitHub Artifact Ingestion

## Purpose

Bring the backlog/delivery surfaces — Issues and PRs — into the artifact table, so evidence linking can connect capabilities to their execution history.

## What This Task Does

- Implements `app/builderops/ckm/ingest_github.py`: fetches Issues and PRs for `RasmusTho/agentic-pkm-mvp` via `gh api` REST (per the repo's rate-limit routing posture: REST, not GraphQL), yielding artifact records with `artifact_kind` `issue` / `pull_request`, capturing number, title, state, labels, linked-PR/closing refs, changed-file list (PRs), and body-referenced doc paths / `#NNNN` cross-references (parsed mechanically, stored as raw ref lists for CKM-05).
- Incremental watermark via `updated_at` cursor per kind (`since=` param); re-runs fetch only updated items (INV-CKM-7).
- **Offline degrade:** when `gh` is unavailable or rate-limited, the adapter reports `skipped (offline)` and leaves watermarks untouched — never fails the whole ingest run, never half-advances a watermark (INV-CKM-5).
- CLI: `python -m app.builderops ckm ingest --source github` (also included in `--source all`).

## Concretely

```bash
python -m app.builderops ckm ingest --source github
# → "issues: 3140 known (+12 updated), prs: 2050 known (+9 updated); cursor 2026-07-07T09:12:00Z"
# offline:
# → "github: skipped (gh unavailable); watermark unchanged"
```

## Why This Matters

Issues/PRs are the richest maturity evidence for *functional completeness* and *requirement coverage* (delivered slices, closed epics). A watermark that advances on a failed fetch would silently hide evidence forever.

## Acceptance Criteria

- [ ] Adapter normalizes fixture REST payloads into typed records including cross-reference lists (doc paths, `#NNNN`).
  - Verify: `tests/builderops/ckm/test_ingest_github.py::test_rest_payload_normalization_with_refs`
- [ ] Incremental cursor semantics: a second run with an unchanged fixture set ingests zero; an item with newer `updated_at` is re-ingested and upserted (one row, updated fields).
  - Verify: `tests/builderops/ckm/test_ingest_github.py::test_updated_at_cursor_incremental`
- [ ] Offline/rate-limit degrade leaves the watermark untouched and returns a named skip status, asserted through the real ingest entrypoint (enforcement AC — the guard runs on the production call path, not in isolation).
  - Verify: `tests/builderops/ckm/test_ingest_github.py::test_offline_degrade_preserves_watermark_via_entrypoint`
- [ ] No GraphQL calls anywhere in the adapter (REST-only posture).
  - Verify: `tests/builderops/ckm/test_ingest_github.py::test_rest_only_no_graphql`

## How to Verify (Pre-Merge)

- `python -m pytest tests/builderops/ckm/test_ingest_github.py -q` (fixture-driven; no live network in CI)
- One live CLI run locally where `gh` is authenticated; then re-run to confirm ~0 updates.
- Full `pytest -m "not pg"` before PR.

## Out of Scope

- GitHub Projects board state, review comments, CI check runs (future adapters).
- Evidence-edge creation from the captured refs (CKM-05 consumes them).
- Any GitHub *write* (INV-CKM-2).

## Related Docs

- `docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 5.14`, `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md :: Cross-Task Invariants`

## Related GitHub Issues

One issue. Blocked by CKM-01; parallel with CKM-02/CKM-03. TCD hint: Sonnet / medium (API adapter with fixtures; degrade path needs care).
