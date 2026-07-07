---
name: Verify Control Surface Round Trip On Test Channel
description: Real-runtime receipt that an app-shaped `_heimdal/**` edit (provenance-tagged, read-merge-write) round-trips through the hub test channel — watcher ingest to runtime state — proving the cross-writer seam B1 rides.
task_id: YGGSHELL-05
source_anchor: docs/contracts/MIMER_CLIENT_CONTRACT.md :: §5 (Bifrost shells read/write the `_heimdal/**` control surface)
parent_capability: Yggdrasil App Shell Completion
prerequisites: [YGGSHELL-02]
depends_on: [TAG_WRITER_PROVENANCE_AND_CITE_DECIDED_CONSISTENCY_MODEL.md]
can_parallelize_with: [PROVE_UAT_JOURNEYS_IN_SIMULATOR_AND_ON_DEVICE]
---

# Verify Control Surface Round Trip On Test Channel

Target repo: **`RasmusTho/agentic-pkm-mvp`** (hub). Runs on the hub **test channel** host — the
operator laptop has no runtime deps by design; real-runtime receipts are produced on the test
channel (`docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md :: test channel`).

## Purpose

B1's whole value proposition is one seam: the phone steers the runtime **through vault notes**. That
seam has been proven from the runtime side (Epic A #3019: `_heimdal/**` is a live writable control
surface) and built from the client side (bifrost PR #2), but no receipt yet shows a *client-shaped*
edit — read-merge-write, provenance-tagged, atomic replace — being observed by the hub runtime.
This task produces that receipt.

## What This Task Does

On the test channel host, against the test channel's configured vault and runtime:

1. Record the runtime's current view of one `_heimdal/**` control note (e.g. the interests note):
   note content + the relevant runtime state (settings-explain / Heimdal state endpoint) + trace of
   the watcher's last ingest of that path.
2. Apply an **app-shaped edit** to that note directly on the filesystem, exactly as the bifrost
   client would after YGGSHELL-01/02: read → mutate one human-owned field (e.g. add a watchlist
   entry) → re-serialize preserving all foreign fields → atomic replace → `agent_provenance` block
   (`author: bifrost-ios`, `origin: direct-fs`). No hub code changes; this is a verification
   procedure, not a feature.
3. Observe the watcher ingest the change (mtime + sha256 path) and the runtime state reflect the
   edit; capture the before/after evidence.
4. Confirm no foreign field on the note was disturbed and the runtime did not misclassify or reject
   the provenance-tagged note.
5. Post the receipt (steps, evidence, runtime build/`/version`, channel identity) as a comment on
   #3023.

If the round-trip fails (watcher misses the edit, runtime rejects or misreads the provenance block,
foreign fields disturbed), that is a **bug** against the hub ingest/Heimdal path: route through
`bug-to-issue`, link it on #3023, and leave this task open — the closure task gates on a passing
receipt (spec INV-B1C-4).

## Concretely

```bash
# On the test channel host (test channel env; paths per DEFINE_CHANNEL_IDENTITY):
curl -s localhost:<test-port>/version           # record runtime build
# 1. capture before-state (note bytes + runtime view of interests)
# 2. python/one-shot script: read note -> add watchlist entry + agent_provenance -> atomic replace
# 3. tail watcher log / poll runtime until the change is reflected
# 4. diff note frontmatter: only intended field + provenance changed
```

Receipt shape on #3023: "Test-channel round-trip receipt — channel: test, runtime build: <sha>,
note: `_heimdal/<name>.md`, edit applied <utc>, watcher ingest observed <utc>, runtime state
reflected <utc>, foreign fields intact: yes/no."

## Why This Matters

Without this receipt, B1 closure would rest on client-side CI plus Epic A's runtime-side proof —
two halves that have never been shown meeting in the middle on a real channel. The specific failure
this catches: the app's YAML re-serialization or provenance block subtly breaking the hub parser's
expectations of `_heimdal/**` note shape (the exact G3/F7 drift risk the contract names), which no
Swift test and no Python unit test can see alone.

## Acceptance Criteria

- [ ] An app-shaped, provenance-tagged edit to a `_heimdal/**` note on the test channel's vault is
  ingested by the test watcher and reflected in runtime state, with before/after evidence.
  `Verify:` runtime receipt — comment on `RasmusTho/agentic-pkm-mvp#3023` with the evidence listed
  above.
- [ ] The edit disturbed no foreign frontmatter field, and the provenance block did not cause
  misclassification or rejection at ingest. `Verify:` same receipt — frontmatter diff section shows
  only the intended field + `agent_provenance` changed; ingest log shows normal classification.
- [ ] Channel isolation respected: everything ran on the test channel (test DB, test vault, test
  runtime); prod untouched. `Verify:` same receipt — channel identity block per
  `docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md :: test channel`.

## How to Verify (Pre-Merge)

This task ships no repo code; its deliverable IS the verification receipt on #3023. "Pre-merge"
here means pre-closure: the receipt must exist and name its evidence before
RECONCILE_AND_CLOSE_B1_TRACKING may proceed. If a small helper script is worth keeping, it lands
under `scripts/` via a normal implementation PR with the standard gates — otherwise the procedure
stays fully documented in the receipt.

## Out of Scope

- Fixing any ingest/parser bug found — that is new bug intake (`bug-to-issue`), not this task.
- Concurrent-writer stress testing / conflict staging — ADR-0055 enactment (#3132) territory.
- Running an actual iPhone against the test channel vault — the app-shaped filesystem edit is the
  contract-faithful stand-in (same bytes on disk); eyes-on-device is YGGSHELL-04's job.

## Related Docs

- `docs/contracts/MIMER_CLIENT_CONTRACT.md` §5 (Bifrost `_heimdal/**` surface), §6 (write
  discipline), §9 F7 (note-shape drift risk)
- `docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md` (test channel identity)
- `docs/ENVIRONMENTS.md` (channel/vault terminology)
- `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` (items 4–5 — what "app-shaped" means)

## Related GitHub Issues

One hub issue (`type:task`; `agent:blocked` until YGGSHELL-02 merges in bifrost, then
`agent:ready`), linking #3023. TCD hint: Sonnet / medium effort — a scripted operational procedure
with crisp pass/fail evidence; escalate only if the round-trip fails and diagnosis begins.
