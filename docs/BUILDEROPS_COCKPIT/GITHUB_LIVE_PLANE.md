---
name: GitHub Live Plane
description: Join the live GitHub plane (issues, PRs, checks) at read time with its own freshness and refused-claim degradation
task_id: BOPS-COCKPIT-03
source_anchor: "docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md :: RQ1 — Join keys per level pair"
parent_capability: BuilderOps Cockpit
github_issue: 4450
prerequisites: [BOPS-COCKPIT-01]
depends_on: [REGISTRY_READ_TIME_JOIN.md]
can_parallelize_with: [INDUCED_FAILURE_JOURNEYS.md, DOCS_PLANE_CAPABILITY_LANES.md, COGNITIVE_LOAD_SIBLING.md]
---

# GitHub Live Plane

## Purpose

The delivered join sees GitHub only through the dispatcher's sync mirror, so its GitHub-derived
fields are only as fresh as the last `dispatcher pull`. The delivery authority itself — open PRs,
Governing-Issue edges, check states, issue labels and URLs — must join live, with the plane's
freshness being the read instant and every failure degrading to a refused claim.

## What This Task Does

- Adds a GitHub reader to `app/builderops/cockpit_registry.py` (or a sibling module it calls) that
  fetches, at render time via REST: open issues and PRs for the repository, PR→issue edges from
  `Governing-Issue`/closing keywords in PR bodies, check/CI state per PR head SHA, and the branch
  list (so the owner's "branch but no PR" deficiency becomes a computable predicate in
  BOPS-COCKPIT-04). Joined on issue number / PR number / SHA — the spine the audit proves
  machine-keyed (INV-DG-1) — and scoped by repository (#4470): one live read covers one repo, while
  the dispatcher store carries a `repo` per task, and those numbers are unique only *within* a
  repository. A task outside the configured repo sees no live snapshot at all, so it can neither
  inherit another repo's PR nor vouch for one as already-synced. Same key as the pre-existing
  verification-runs join.
- Registers `github-live` as a read source with `last_successful_read` = the call instant, removing
  it from `UNREAD_PLANES`. Per decision Q5: no cache that survives a reload; a failed or
  rate-limited read yields the refused-claim state for GitHub-owned facts, never stale data
  presented as fresh. Mirror-derived fields **must begin naming the mirror's own watermark**
  (`sync_state.last_pull_at`) — today the delivered registry renders them under the
  dispatcher-store pill's SQLite read instant, which implies a liveness the mirror does not have.
- Upgrades rung classes where live keys now exist: `pr` and `ci_sha` rungs become `proven` from
  live PR + check data; threads with a branch/PR but no dispatcher task appear rather than being
  invisible.
- Per-SHA partial failure is recorded, not swallowed (#4471). One PR's check-status call failing
  does not refuse the whole plane — the rest of the snapshot is still fresh — but the SHA lands in
  `GithubLiveSnapshot.check_read_failures` rather than simply missing from `checks`. Downstream,
  the `ci_sha` rung names the unread read and the "PR with no CI on head SHA" predicate withholds:
  that predicate asserts something about GitHub, and a failed read of ours is not evidence for it.
- Every card gains its authority out-link (issue/PR URL) from the live read, independent of the
  sync mirror's structurally empty fields (audit F9) — rendered in the `out` button class.
- Auth/binding: the token available to **the process that runs the read** — `gh` resolves
  `GITHUB_TOKEN`/`GH_TOKEN` from its own environment. Unauthenticated or missing-token environments
  degrade to the refused claim, and tests must not require network.

## Concretely

```
curl -s localhost:18001/api/cockpit/registry | jq '.sources[] | select(.name=="github-live")'
```

Expected: `state: "fresh"` with the call's own instant — or `state: "unavailable"` with GitHub-owned
counts refused, never zeroed, when the API is unreachable or rate-limited.

### What makes that command answer `fresh` (#4484)

The read runs **inside the `api` container**, not on the host, so the enablement path is three
committed things plus one host-supplied value:

1. **The transport exists in the image.** `Dockerfile`'s runtime stage installs `gh` alongside
   `ffmpeg`/`espeak-ng` (a plain Debian trixie/main package; no third-party apt source). Before
   #4484 it was absent, so `_run_gh` raised `gh CLI not found` on the first call in every channel
   regardless of configuration.
2. **The repo slug is committed for dev and prod.** `docker-compose.dev.yml :: api` and
   `docker-compose.prod.yml :: api` set
   `COCKPIT_GITHUB_REPO=RasmusTho/agentic-pkm-mvp`. Dev is the channel the command above names
   (18001); prod's committed identity is consumed by the separately promoted devUI path.
3. **`test` deliberately leaves it unset.** It renders *not enabled* rather than broken (EXT-8,
   #4481). A committed repository identity is non-secret configuration; it does not prove that a
   credential is present or that the corresponding revision is running on a host.
4. **The token is host-supplied.** `GITHUB_TOKEN` reaches the container on the `api` consumer's
   already-declared host-secret env layer (`HOST_SECRET_RUNTIME_ENV_FILE_API` in
   `docker-compose.yaml :: api`, #4422) — the same layer that delivers `HEIMDAL_RAW_STORE_KEY`. No
   token is committed to the repo, and a repo-scoped read-only token is sufficient: the plane issues
   GET requests only and persists nothing.

With the slug set and the token absent, the plane is *configured but failing* — an honest outage,
not an opt-out. With the slug unset, nobody asked for it and nothing is claimed either way.

The committed repository binding is not deployment or credential-presence evidence. For prod,
`github.token` and the coupled `heimdal.raw-store-key` must both be present through the declared
`heimdal-api-ingress` host-secret consumer before the governed layer can support the read. The
value-free prerequisite command is documented in `docs/OPERATIONS.md`; it neither provisions nor
prints either credential.

## Why This Matters

Without this plane the register can contradict GitHub within minutes of owner action (the red-team
finding: owner merges at 09:00, surface projected 08:50). Live reads with named instants are the
only posture that never creates a second truth; the rate-limit budget is real (builder agents
already drain GraphQL first), which is why failure must be a visible refusal instead of a retry
loop or a silent stale render.

## Acceptance Criteria

- [ ] `github-live` is a named source whose freshness is the read instant; on read failure every
      GitHub-owned fact degrades to the refused claim, never zero and never stale-as-fresh
  - Verify: `tests/builderops/test_cockpit_github_plane.py::test_github_failure_refuses_not_zeroes`
    (enforcement AC: exercises `build_registry` with the GitHub reader injected to fail, asserting
    the production join path emits the refusal)
- [ ] PR and CI/sha rungs classify `proven` from live PR + check keys; threads visible in GitHub
      but absent from the dispatcher store render as cards instead of disappearing
  - Verify: `tests/builderops/test_cockpit_github_plane.py::test_live_keys_upgrade_rungs_and_surface_unsynced_threads`
- [ ] Every card carries its authority out-link from the live read
  - Verify: `tests/builderops/test_cockpit_github_plane.py::test_cards_carry_authority_outlinks`
- [ ] No persisted cache: two consecutive renders each perform their own read; nothing GitHub-derived
      survives a process restart
  - Verify: `tests/builderops/test_cockpit_github_plane.py::test_no_cross_render_cache`
- [ ] Mirror-derived fields name the sync mirror's own watermark (`sync_state.last_pull_at`), not
      the store-read instant
  - Verify: `tests/builderops/test_cockpit_github_plane.py::test_mirror_fields_name_mirror_watermark`

## How to Verify (Pre-Merge)

- `pytest tests/builderops/test_cockpit_github_plane.py -m "not pg"` — all tests run with an
  injected fake reader; no network in CI.
- Manual once on the host: load `/cockpit` with credentials present and confirm the pill shows the
  render instant; disconnect and confirm refusal.

## Out of Scope

- Any GraphQL usage (REST only — GraphQL budget dies first on this host).
- The mirror-cache posture and its fourth pill state (ADR-0062 independent-service home; decision
  Q5 defers it).
- Parent/child prose-edge parsing and chain-position semantics (BOPS-COCKPIT-04 consumes this
  plane; this task only supplies keys, checks, and links).
- Any write to GitHub; any change to dispatcher sync behavior — `app/dispatcher/sync_github.py`
  and `scripts/issue_pickup_claim.sh` are owned by the filed data-edge issues #4440 (single-source
  `task_id`) and #4441 (sync_state labels/URL); consume the keys, never write them.

## Restart / Durability Posture

Nothing fetched survives a restart or reload; each render pays its own reads. The user consequence
is per-render latency against GitHub and honest refusal during outages — accepted by decision Q5 in
`DESIGN_DECISIONS.md`.

## Related Docs

- `docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: Q5`
- `docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md` (F1, F9, RQ1)
- `.codex/skills/_shared/CI_WAIT_CONTRACT.md` (REST-over-GraphQL budget discipline)

## Related GitHub Issues

One bounded issue. Reference "Implements BUILDEROPS_COCKPIT/GITHUB_LIVE_PLANE". Coordinates with
the filed delivery-graph data-edge issues #4440/#4441 — this task never modifies
`app/dispatcher/sync_github.py` or `scripts/issue_pickup_claim.sh` (their scope).
