---
name: Repo Artifact Ingestion
description: Deterministic local adapters that normalize docs, ADRs, spec directories, tests, schemas, source, and git history into CKM artifact records with watermarks
task_id: CKM-03
source_anchor: docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 5.14 Data Sources
parent_capability: Capability Knowledge Model
prerequisites: [CKM-01]
depends_on: [CKM_STORE_AND_OBJECT_MODEL.md]
can_parallelize_with: [Capability Registry Seed, GitHub Artifact Ingestion]
---

# Repo Artifact Ingestion

## Purpose

Turn the repository's local artifact surfaces into normalized `ckm_artifact` records so linkers and assessment have deterministic raw material. Local-only, no network, no LLM.

## What This Task Does

- Implements `app/builderops/ckm/ingest_repo.py` with one adapter per source, each yielding artifact records `(natural_key, artifact_kind, payload_summary, provenance, source_watermark)`:
  - **docs adapter** — walks `docs/**/*.md`; `artifact_kind` from location/header (`adr` for `docs/adr/`, `spec` for spec directories with task frontmatter, `doc` otherwise); captures the `State:` header line and title as the payload summary.
  - **test adapter** — walks `tests/**/test_*.py`; records module path + test names (AST-level listing, no execution).
  - **source adapter** — walks `app/**/*.py`; records module path + top-level docstring first line.
  - **schema adapter** — walks `schemas/**/*.json`; records each JSON schema as a provenance-bearing document artifact so deterministic matrix citations have a resolvable producer.
  - **git adapter** — `git log` over a bounded window (configurable, default: since last watermark) yielding commit records (sha, subject, changed paths).
- Watermarking per source (`docs`, `tests`, `source`, `schemas`, `git`): stores the last-ingested state (HEAD sha for git; content hash set for tree walks) in a `ckm_watermark` helper table; re-runs ingest only what changed (INV-CKM-5, INV-CKM-7).
- CLI: `python -m app.builderops ckm ingest --source repo`.

## Concretely

```bash
python -m app.builderops ckm ingest --source repo
# → "docs: 412 artifacts (+3), tests: 388 (+1), source: 290 (0), schemas: 27 (0), git: 5210 commits (+17)"
```

## Why This Matters

Everything downstream is only as honest as ingestion: a missed artifact class shows up later as a phantom gap, and a watermark that lies makes INV-CKM-5 staleness reporting meaningless.

## Acceptance Criteria

- [ ] All five tree adapters plus git produce records with non-null natural keys, kinds, and provenance over a fixture tree, including JSON schemas required by the traceability matrix.
  - Verify: `tests/builderops/ckm/test_ingest_repo.py::test_adapters_yield_typed_provenanced_records`
- [ ] Re-ingestion over an unchanged tree inserts zero new rows; touching one doc re-ingests exactly that artifact and advances the watermark.
  - Verify: `tests/builderops/ckm/test_ingest_repo.py::test_incremental_watermark_semantics`
- [ ] ADRs and spec-directory task files get their specific kinds (`adr`, `spec`), not generic `doc`, on real repo paths.
  - Verify: `tests/builderops/ckm/test_ingest_repo.py::test_kind_classification_for_adr_and_spec`
- [ ] Ingestion never mutates the working tree, never shells out to the network, and completes on the real repo in bounded time (< 60 s cold on the dev laptop profile).
  - Verify: `tests/builderops/ckm/test_ingest_repo.py::test_ingest_is_readonly_and_offline`

## How to Verify (Pre-Merge)

- `python -m pytest tests/builderops/ckm/test_ingest_repo.py -q`
- One cold + one warm CLI run against the live repo; confirm warm run reports 0 changes.
- Full `pytest -m "not pg"` before PR.

## Out of Scope

- GitHub-hosted artifacts (CKM-04), evidence edges (CKM-05/06), AI-session transcripts (future source; needs a durable transcript surface first).
- Parsing file *contents* beyond kind/summary — semantic reading belongs to CKM-06.

## Related Docs

- `docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 5.14`, `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md :: Cross-Task Invariants`

## Related GitHub Issues

One issue. Blocked by CKM-01; parallel with CKM-02/CKM-04. TCD hint: Sonnet / medium (mechanical walkers with clear tests).
