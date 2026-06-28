---
name: Runtime Version Marker
description: >
  Bake git SHA + build time into the image and expose them via /version and a
  version field in /api/health so the running commit is observable.
task_id: OBSSTAB-05
source_anchor: "app/version.py :: version ; Dockerfile :: build args"
parent_capability: Observability Stabilization
prerequisites: []
depends_on: []
can_parallelize_with:
  - READINESS_REFLECTS_DEPENDENCIES
  - AUDIT_WRITER_STOPS_LYING
  - DEV_DB_SNAPSHOT_RESTORE
---

# Runtime Version Marker

## Purpose

Make the running commit observable at runtime so prod-vs-main divergence is
visible at a glance and a behaviour change can be tied to a specific deploy.
This complements issue #2527 (dirty-main deploy reconciliation) by making the
divergence loud; it does not replace the deploy source-of-truth fix.

## What This Task Does

1. Add `ARG VCS_REF` and `ARG BUILT_AT` to `Dockerfile`, bake them as `LABEL`
   metadata, **and persist them into the image environment with
   `ENV VCS_REF=$VCS_REF` / `ENV BUILT_AT=$BUILT_AT`**; pass them at build time
   via `--build-arg`. A bare `ARG`/`LABEL` is *not* readable via `os.getenv` at
   runtime — without the `ENV` lines `/version` would silently fall back to
   "unknown" in the built image and the monkeypatched unit tests would not catch
   it (they inject env directly). (Alternatively, read the `LABEL` via
   `docker inspect`, but the `ENV` persist is the simplest runtime-readable path.)
2. Add `app/version.py :: get_runtime_version()` that reads `VCS_REF` /
   `BUILT_AT` from the env vars persisted in step 1 (or a fallback shelling to
   `git rev-parse HEAD` for local dev runs without Docker).
3. Register a `/version` route returning `{"git_sha": "…", "built_at": "…"}`.
4. Extend `run_health` in `app/cli/health.py` to include a top-level
   `"version"` field carrying the same SHA.
5. Surface the SHA in `verify-runtime` output.

The static SoT strings at `app/version.py:1-4` (`SOT_BASELINE`, `SOT_FORWARD`,
`SOT_LABEL`, `SOT_VERSION`) are unchanged — they are doc/governance constants,
not the runtime identity being added here.

## Concretely

```bash
# Build with SHA baked in
docker build --build-arg VCS_REF=$(git rev-parse HEAD) \
             --build-arg BUILT_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
             -t pkm-api .

# /version returns the baked SHA
curl -s localhost:18000/version
# {"git_sha":"ce0e5c46…","built_at":"2026-06-27T10:00:00Z"}

# /api/health carries the same SHA in .version
curl -s localhost:18000/api/health | jq .version
# "ce0e5c46…"

# SHA matches the built checkout
git rev-parse HEAD
# ce0e5c46…
```

## Why This Matters

No runtime endpoint exposes a git SHA today (`Dockerfile` has no ARG/LABEL;
`app/version.py` only carries static doc-version strings). Prod deploys from a
dirty `main` checkout (#2527), so "which commit is prod running?" is
unanswerable and operators debug against the wrong source during incidents
(risk R7). This task makes the divergence immediately visible without requiring
SSH access to the container.

## Acceptance Criteria

- [ ] `GET /version` returns the git SHA matching the built checkout.
  - Verify: `tests/api/test_version_marker.py::test_version_matches_git_sha`
- [ ] `/api/health` includes a `version` field carrying the same SHA.
  - Verify: `tests/api/test_version_marker.py::test_api_health_includes_version`
- [ ] `/version` value is not the static doc-version string from `app/version.py:4`.
  - Verify: `tests/api/test_version_marker.py::test_version_not_static_doc_version`

## How to Verify (Pre-Merge)

```bash
# Unit tests (no Docker required — tests inject VCS_REF via monkeypatch/env)
pytest tests/api/test_version_marker.py -v

# Full not-pg suite to confirm no regressions
pytest -m "not pg" --timeout 120 -q
```

## Out of Scope

- Reconciling the dirty-main deploy itself (#2527, governance lane).
- Version-bump / changelog policy.
- Surfacing build metadata in the Companion UI.

## Related Docs

- `app/version.py` — static SoT constants (unchanged)
- `Dockerfile` — receives the new `ARG`/`LABEL` lines
- `app/cli/health.py :: run_health` — gains the `version` field
- `docs/OPERATIONS.md` — may receive a note on reading `/version` in runbooks

## Related GitHub Issues

Child of the parent Observability Stabilization feature issue. Cross-links
#2527 (prod-runs-dirty-main). Independent of other OBSSTAB tasks;
parallelizable.
