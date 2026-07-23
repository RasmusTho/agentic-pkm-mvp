---
name: Deploy Karakeep As A Managed Service
description: Add reproducible mac-mini deployment, health, restart, update, and backup contracts without committed secrets.
task_id: KMA-02
source_anchor: "docs/audits/APP_MCP_CONNECTIVITY_2026-07-07.md :: §5 B2"
parent_capability: Karakeep Mimer Acquisition
prerequisites: [KMA-01]
depends_on: [DEFINE_READING_SOURCE_AND_CANDIDATE_CONTRACT]
can_parallelize_with: [FETCH_KARAKEEP_READING_EVIDENCE]
---

# Deploy Karakeep As A Managed Service

## Purpose

Make the selected self-hosted source operable and observable on the mac mini without turning machine-
specific endpoint or credential values into repo truth.

## What This Task Does

Add the repo-owned deployment manifest/runbook integration, pinned image policy, durable volumes,
health/readiness check, restart behavior, backup/update procedure, and fail-loud startup validation.
Configuration references existing secret/env mechanisms; committed fixtures use placeholders only.
The service is Heimdal's external source dependency; Mimer has no direct Karakeep connection.

## Concretely

A standard service lifecycle can start, stop, inspect, update, and restore Karakeep. Heimdal fetch
does not run unless health is green; Mimer consumption of already-published evidence remains
available when the service is down. Logs and rendered configuration are secret-safe.

## Why This Matters

The acquisition worker cannot be more reliable than its source service; explicit durability and
health behavior prevent an unavailable or half-upgraded source from looking like an empty feed.

## SBS Impact

Product/Runtime: OEF primary, Heimdal/EBF secondary. Deployment/config write class; the dependency is
explicitly on Heimdal's side of the boundary. No Builder System or public-ingress change.

## Restart / Durability Posture

Service restart preserves database/assets volumes. A failed migration/update leaves the previous
version recoverable under the runbook. Worker cursor state is separate and is not stored in the
container lifecycle.

The repo-owned manifest is [`docker-compose.karakeep.yml`](../../docker-compose.karakeep.yml): a
pinned image (`ghcr.io/karakeep-app/karakeep:<version>`), the durable named volumes `karakeep-data`
(bookmarks/assets) and `karakeep-meilisearch-data` (search index), a web-root healthcheck, and
`restart: unless-stopped`. Every secret and the private endpoint ride the operator-owned, gitignored
`config/karakeep.env` (template: [`config/karakeep.env.example`](../../config/karakeep.env.example));
the committed manifest and template carry no credential or endpoint value. The service binds to
loopback only — there is no public ingress. The fail-loud gate
`app.heimdal.karakeep_service.assert_fetch_ready` refuses Heimdal acquisition when a required config
reference is absent or health is red, while Mimer replay of already-published evidence is unaffected.

### Backup / update / rollback runbook

All commands run from the repo root on the mac mini with
`docker compose -f docker-compose.karakeep.yml` (abbreviated `compose` below).

- **Backup (durable data):** the durable data is the named volumes `karakeep-data` and
  `karakeep-meilisearch-data`. Snapshot them while the service is stopped or quiescent:
  `compose stop` then, for each volume,
  `docker run --rm -v karakeep-data:/data -v "$PWD/backup":/backup alpine tar czf /backup/karakeep-data.tgz -C /data .`
  (repeat for `karakeep-meilisearch-data`). **Verification check:** confirm each archive is non-empty
  and lists entries — `tar tzf backup/karakeep-data.tgz | head` — before treating the backup as good.
- **Update:** bump the pinned image tag in `docker-compose.karakeep.yml`, take a fresh backup (above),
  then `compose pull && compose up -d`. **Verification check:** `compose ps` shows the service
  `healthy` and `docker inspect --format '{{.Config.Image}}' <container>` reports the new pinned tag.
  A half-upgraded or unhealthy service is caught here (and by `assert_fetch_ready`) before any fetch.
- **Rollback:** restore the previous pinned tag in the manifest and `compose up -d`; if data must be
  reverted, `compose down` (never `-v`, which would delete the durable volumes), restore the volume
  archives with the inverse `tar x` into each named volume, then `compose up -d`. **Verification
  check:** `compose ps` reports `healthy` and a spot read in the Karakeep UI shows the expected
  bookmarks. The durable volumes survive `compose down`/restart; only `down -v` destroys them.

## Acceptance Criteria

- [ ] Deployment pins an explicit image/version and declares durable volumes, healthcheck, and
  restart behavior. Verify: `tests/ops/test_karakeep_service_contract.py::test_service_manifest_is_pinned_persistent_and_health_checked`.
- [ ] Startup fails before acquisition when required config references are absent or health is red.
  Verify: `tests/ops/test_karakeep_service_contract.py::test_unhealthy_service_blocks_heimdal_fetch_not_mimer_replay`.
- [ ] Committed manifest, rendered test config, and logs contain no credential or private endpoint
  value. Verify: `tests/ops/test_karakeep_service_contract.py::test_service_manifest_is_health_checked_and_secret_free`.
- [ ] Backup/update/rollback steps name durable data and a verification check. Verify: doc writeback
  at `docs/KARAKEEP_MIMER_ACQUISITION/DEPLOY_KARAKEEP_AS_A_MANAGED_SERVICE.md :: Restart / Durability Posture`.

## How to Verify (Pre-Merge)

- `pytest -q tests/ops/test_karakeep_service_contract.py`
- `python3 scripts/docs_guard.py`

## Out of Scope

Choosing or publishing the private endpoint, credential values, DNS/firewall changes, public ingress,
Karakeep product customization, and interactive MCP configuration.

## Related Docs

- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
- `docs/ENVIRONMENTS.md`
- `docs/runbooks/` deployment patterns

## Related GitHub Issues

Issue #3373 after KMA-01; parallel with KMA-03. TCD hint: Sonnet/standard model, medium reasoning;
mechanical deployment with high-value secret and rollback checks.
