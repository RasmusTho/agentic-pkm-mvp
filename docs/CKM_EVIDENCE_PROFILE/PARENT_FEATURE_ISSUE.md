State: Filed parent feature issue contract. [#4089](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4089) is the authoritative live validation hub, open with `agent:blocked`; children #4090–#4092 are open, with #4091–#4092 carrying `agent:blocked` in serial dependency order. This parent is never a pickup issue.

# CKM Evidence Profile — Parent Validation Hub

## Purpose

Live parent [#4089](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4089) holds the delivery
receipts and terminal acceptance evidence for the Phase 1 specification at
[README.md](README.md). It is the authoritative backlog and validation surface; this file is the
local pointer and stable map, not a duplicate issue contract.

## Child map

1. CKM-EP-01 — [#4090](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4090) —
   [SCALAR_RETIREMENT.md](SCALAR_RETIREMENT.md). Open; first serial slice.
2. CKM-EP-02 — [#4091](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4091) —
   [TRISTATE_STATUS.md](TRISTATE_STATUS.md). Open, `agent:blocked`; follows CKM-EP-01.
3. CKM-EP-03 — [#4092](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4092) —
   [SUBSYSTEM_COUNTS_VIEW.md](SUBSYSTEM_COUNTS_VIEW.md). Open, `agent:blocked`; follows the serial
   execution path.

## Validation-hub map

- The child PRs supply their exact `Verify:` results, current-SHA CI, local review, owner-doc result,
  and parent-handoff receipts to #4089.
- The parent records the combined INV-EP-6 authorized real-store replay, including the CKM-EP-01
  Retrieval result, CKM-EP-02 named documentation-absence result, and CKM-EP-03 count and
  shared-evidence-indicator results.
- Parent closure requires every child and the terminal acceptance target to be repo-verifiable. Until
  then, live issue state—not this pointer—governs pickup and lifecycle status.

## Source anchors

- `docs/CKM_EVIDENCE_PROFILE/README.md :: Phase boundary (what Phase 1 is and is not)`
- `docs/CKM_EVIDENCE_PROFILE/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/CKM_EVIDENCE_PROFILE/README.md :: Acceptance criteria (capability level)`
- `docs/CKM_EVIDENCE_PROFILE/README.md :: Verification and acceptance path`
