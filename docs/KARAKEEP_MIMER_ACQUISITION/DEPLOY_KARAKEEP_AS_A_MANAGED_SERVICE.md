---
name: Deploy Karakeep As A Managed Service
description: Define a reproducible private-service manifest and health, restart, update, and backup contracts without committed secrets.
task_id: KMA-02
source_anchor: "docs/audits/APP_MCP_CONNECTIVITY_2026-07-07.md :: §5 B2"
parent_capability: Karakeep Mimer Acquisition
prerequisites: [KMA-01]
depends_on: [DEFINE_READING_SOURCE_AND_CANDIDATE_CONTRACT]
can_parallelize_with: [FETCH_KARAKEEP_READING_EVIDENCE]
---

# Deploy Karakeep As A Managed Service

## Purpose

Make the selected self-hosted source operable and observable without turning machine-specific endpoint
or credential values into repo truth. The supported non-production roles are `ygg-dev` and
`ygg-test`; Demerzel/Mac mini is the authenticated controller. Repository delivery establishes the
deployment path, not a live installation or the KMA-06 source-to-candidate acceptance on #3367.

## What This Task Does

Add the repo-owned deployment manifest/runbook integration, pinned image policy, durable volumes,
health/readiness check, restart behavior, backup/update procedure, and fail-loud startup validation.
Configuration references existing secret/env mechanisms; committed fixtures use placeholders only.
The service is Heimdal's external source dependency; Mimer has no direct Karakeep connection.

## Concretely

A standard service lifecycle can start, stop, inspect, update, and restore Karakeep. Heimdal fetch
does not run unless health is green; Mimer consumption of already-published evidence remains
available when the service is down. Logs and rendered configuration are secret-safe.

### Test-channel placement and prerequisites

Issue #6014 adds `scripts/karakeep-deploy <dev|test> --revision <installed-control-checkout-SHA>`.
The command selects the exact SSH alias, holds the existing host-secret controller admission,
checks only the two service consumers, and calls the existing root-only BWS supervisor socket.
`prod` is refused before secret resolution or SSH. It never moves a Mimer channel pin or starts a
Product worker. Install the reviewed code in the existing root-owned control checkout and refresh
the installed launcher from `scripts/postgres_deploy_service.py` before requesting Karakeep actions.
The existing supervised encrypted-reader unit must be active with its channel configuration;
there is no generic VM secret helper, direct BWS writer, or VM admin token.

Qualification remains an operational action outside Git. Preserve the existing controller
`qualification.json` and its accepted host-custody model described by the current #5667 receipt;
do not attest executable confinement. On each target, install root-owned mode-0600
`/etc/yggdrasil/karakeep/<channel>.json`, with exactly `channel`, `server_url`, `qualification_ref`,
and `qualified_at`. The reference must be a redacted #3367 operations comment and the UTC ISO time
must be current (within 24 hours for a new installation/restart request). Record host/engine and
control-checkout identities, SSH/sudo and reader readiness, port ownership, private forwarding
qualification, selected credential status, and the scope of the authorization without endpoint or
credential values. Actual preflight also checks the host role, local Docker socket, unchanged
manifest at the selected revision, project containers/volumes and exclusive loopback port ownership.
`server_url` may name only an observed SSH local forwarding route on loopback with a port in
1024–65535; it does not change the host's loopback-only port-3000 publication. DEV and TEST browser
tunnels can use separate local ports. Docker and Compose commands receive no reader credential.

The finite BWS bindings in `config/secrets/host_secret_contract.json` are channel identities under
the existing `non-prod` project. All grants below exist only on `dev` and `test`:

| Identity | Consumer | Delivery / purpose |
| --- | --- | --- |
| `karakeep.session-token` | `karakeep-service-web` | `/run` web handle as `NEXTAUTH_SECRET` |
| `karakeep.search-token` | `karakeep-service-web`, `karakeep-service-search` | Separate `/run` handles as `MEILI_MASTER_KEY` |
| `karakeep.api-key` | `heimdal-karakeep-fetch` | Issuer-created `KARAKEEP_API_TOKEN`; never a service credential |
| `karakeep.account-pass` | `karakeep-account-setup` | Password for subsequent authorized account setup/recovery only |

On the controller, `scripts/secrets prepare-karakeep dev` creates only absent service keys through
the existing writer; reruns preserve them. Repeat with `test` for independent channel identities.
No acquisition API key or account password is required to start the service. Existing malformed
keys refuse preparation; imports cannot replace retained service keys. Generic `generate`/`rotate`
policy remains unchanged. Account password and issuer-generated API key imports use
`scripts/secrets import <channel> <identity> --stdin`, with exact in-memory input and no raw output.
The account-setup consumer receives only the password; it cannot borrow service or acquisition
keys. Account identity and Heimdal's `KARAKEEP_BASE_URL` remain qualified operational inputs outside
Git. Karakeep issues the account and API key after service startup; account/issuer automation is not
implemented by this service module.

For separately authorized setup/recovery, the operator may use public
`resolve_host_secret_values(channel=<dev|test>, consumer="karakeep-account-setup", provider="bws", ...)`
with the existing non-prod reader and an admitted check operation. It returns only that consumer's
logical password value in memory and grants no issuer call or write. Normal BWS writes still use
`scripts/secrets import --stdin`. Initial setup may keep the generated password in memory, obtain
issuer success, then import it; API-key issuance/import is separate. Do not use the generic
`host_secret_bootstrap --provider bws` consumer-launch CLI or direct SDK calls for this operator
read; that launch remains refused outside its existing MARR exception. This is the finite setup
consumer's operator path, not another runtime or provider-account administration grant.

For DEV, prepare the two service keys, qualify the existing dev reader/host/config, then run
`scripts/karakeep-deploy dev --revision <installed-control-checkout-SHA>` from the controller.
For TEST, independently qualify its host, reader, identities and forwarding route, then use the
same command with `test`. Inspect the value-free terminal receipt and live health/readback on the
exact host. A successful TEST installation proves service operation only: KMA-06 still requires
real source → Heimdal published evidence → Mimer review-required candidates, separate cursors,
replay and no automatic promotion. Fixture tests, DEV success, and a healthy web root cannot close
#3367 or #5667.

## Why This Matters

The acquisition worker cannot be more reliable than its source service; explicit durability and
health behavior prevent an unavailable or half-upgraded source from looking like an empty feed.

## SBS Impact

Platform and Operations owns the service lifecycle; Heimdal/EBF owns source acquisition and
Security owns secret custody. The boundary change adds finite non-production consumer grants;
Mimer continues to consume published evidence only. No Product semantic or public-ingress change.

## Restart / Durability Posture

Service restart preserves database/assets volumes. A failed migration/update leaves the previous
version recoverable under the runbook. Worker cursor state is separate and is not stored in the
container lifecycle.

The repo-owned manifest is [`docker-compose.karakeep.yml`](../../docker-compose.karakeep.yml): a
pinned image (`ghcr.io/karakeep-app/karakeep:<version>`), the durable named volumes `karakeep-data`
(bookmarks/assets) and `karakeep-meilisearch-data` (search index), a web-root healthcheck, and
`restart: on-failure` for crashes within an admitted runtime. Docker does not start these containers
when its daemon restarts ([Docker restart policy](https://docs.docker.com/engine/containers/start-containers-automatically/)).
The governed unit alone admits daemon/VM startup after reader and journal checks. Its Docker
dependency/restart binding and Docker/multi-user enablement ensure rehydration is not bypassed by
retained container environments. Preflight also rejects a retained autonomous-restart policy.
Compose uses projects `karakeep-dev` and `karakeep-test`, so actual volume
names have the corresponding project prefix. The web and search env handles are distinct root-owned
mode-0600 files in mode-0700 `/run/yggdrasil/karakeep/<channel>`; no persistent ordinary env file is
filled from [`config/karakeep.env.example`](../../config/karakeep.env.example). The standard Docker
service configuration contains the environment needed by those containers and is private host
operational state; never print `docker inspect` without field selection or rendered Compose config.
The reader credential and Heimdal token never enter these containers. The service binds to
loopback only — there is no public ingress. The fail-loud gate
`app.heimdal.karakeep_service.assert_fetch_ready` refuses Heimdal acquisition when a required config
reference is absent or health is red, while Mimer replay of already-published evidence is unaffected.

### Backup / update / rollback runbook

The lifecycle uses the existing VM channel mkdir/flock lock and DeployJournal transitions. It
persists the activating boundary before systemd/Compose effects and records committed only after
both service health states, private bindings, images/volumes and the web probe pass. Loss after
activation retains the pending receipt and channel lock; neither healthy containers nor a timeout
clear it. A rerun reconciles the exact operation ID and immutable request, without creating another
worker. Caller observation has a ten-minute window with backoff; expiry returns a typed pending
failure and releases the caller's lock handle without clearing durable admission. A later status
request can still join the same operation. Unknown state requires authoritative recovery of that original operation; there is no
force/retry override or automatic compensation.

A boot may start between the host's read-only preflight and its durable sent deployment request.
Known refusals before installation admission are bound and fsynced in a finite `refused` namespace
of the same DeployJournal, without changing installation/boot receipts or their locks. This
namespace has no worker or service-effect transition. Exact-ID status finishes interrupted refusal
evidence and returns `aborted`; a lost acknowledgment therefore clears host admission without
replaying deployment. Absence of such a bound request never proves rejection. A refused ID cannot
later become a deployment, and a changed plan cannot borrow its receipt. One cooperating host
controller has at most one unresolved request; no additional writer or authority registry is added.

The existing `bws-owner` lock marker durably binds Karakeep's finite deploy/boot actor, channel and
operation ID. After a terminal receipt, status/retry reconciles only that actor's free matching
lock with the existing Linux reconciliation/atomic-retirement helpers before returning terminal
success or replacing its proof. A live kernel holder, pending operation, foreign marker or
malformed marker refuses reconciliation. PostgreSQL's legacy empty-marker reconciliation cannot
borrow a Karakeep or token-push marker. A crash after canonical lock retirement may leave a detached
value-free tombstone; it cannot occupy the admission slot or become another actor's authority.

- **Restart / boot:** an explicit controller rerun re-resolves service keys and preserves data.
  The installed `yggdrasil-karakeep-<channel>.service` boot unit calls the existing reader supervisor
  to rehydrate `/run` handles after tmpfs loss. Boot requires a committed prior installation and
  its unchanged request/check-out binding. Attempts use a separate boot namespace of the same
  existing DeployJournal protocol and the same VM channel lock. Boot outcomes never replace the
  installation request or terminal ID needed after a lost controller acknowledgment. A pre-effect
  refusal remains retryable once contention clears; a pending boot refuses another boot or
  installation mutation. Boot reuses the approved persisted route and does not require daily requalification
  of that unchanged boot input. Missing keys, pending operations and competing channel locks refuse
  service mutation. Verify the new terminal receipt and both service health states after restart.
- **Backup:** separately authorize maintenance on the exact host and acquire the existing channel
  lock. Stop/quiesce the two services in project `karakeep-<channel>` and snapshot both
  `karakeep-<channel>_karakeep-data` and `karakeep-<channel>_karakeep-meilisearch-data` volumes. For
  each volume, mount it read-only in an approved archive helper and use `tar czf` into an
  owner-controlled backup destination. Verify a nonempty archive with `tar tzf` before accepting
  it; protect source data backups separately from BWS custody. Resume through the reviewed lifecycle
  and verify health plus retained bookmarks. This slice adds no archive/restore command.
- **Update / rollback:** image upgrade and data restoration are outside #6014. Review a pinned
  manifest/lifecycle change and take a verified backup before any future version change. Rollback
  requires an authorized known-good version compatible with retained data; if restoration is needed,
  stop/quiesce the exact channel, restore both verified volume archives, and rehydrate service
  credentials through the governed lifecycle. Never use `down -v` or create replacement credentials
  to mask a failed startup. Verify the exact image, healthy services and expected bookmarks.

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
