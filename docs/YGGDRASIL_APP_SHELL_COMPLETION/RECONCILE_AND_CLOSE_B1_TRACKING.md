---
name: Reconcile And Close B1 Tracking
description: Assemble the full B1 verification ledger on hub #3023, close it truthfully, and update Epic B #3020 and this spec's state lines so no surface still reads as pending.
task_id: YGGSHELL-06
source_anchor: docs/YGGDRASIL_APP_SHELL_COMPLETION/README.md :: Capability acceptance criteria
parent_capability: Yggdrasil App Shell Completion
prerequisites: [YGGSHELL-01, YGGSHELL-02, YGGSHELL-03, YGGSHELL-04, YGGSHELL-05]
depends_on: [ALIGN_VAULT_WRITES_TO_COORDINATED_FILE_ACCESS.md, TAG_WRITER_PROVENANCE_AND_CITE_DECIDED_CONSISTENCY_MODEL.md, FIX_FIRST_DELIVERY_REVIEW_FOLLOWUPS.md, PROVE_UAT_JOURNEYS_IN_SIMULATOR_AND_ON_DEVICE.md, VERIFY_CONTROL_SURFACE_ROUND_TRIP_ON_TEST_CHANNEL.md]
can_parallelize_with: []
---

# Reconcile And Close B1 Tracking

Target repo: **`RasmusTho/agentic-pkm-mvp`** (hub).

## Purpose

#3023 is the cross-repo tracking hub for B1 (per ADR-0050: implementation lands in bifrost, the hub
records coordination and verification). Delivery receipts are accumulating there from two repos;
someone must verify the set is complete, close the issue truthfully, and stop Epic B and the spec
from reading as pending work — the drift class the repo's temporal-doc governance exists to prevent.

## What This Task Does

1. **Verify the ledger is complete** on #3023: bifrost delivery (PR #2 `b9e9e7c`, PR #3 `b77cb205`),
   the three convergence merges (YGGSHELL-01/02/03 bifrost PRs with green CI), the UAT receipt
   (YGGSHELL-04, including the operator's device walkthrough), and the test-channel round-trip
   receipt (YGGSHELL-05). Each of #3023's three ACs must map to named evidence.
2. **Check the box state**: tick #3023's AC checkboxes with an evidence pointer per AC (edit the
   body; the repaired Verify targets from 2026-07-07 point at
   `docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md :: §1` and the manual UAT).
3. **Close #3023** with a closing comment summarizing the ledger (one screenful, links not prose).
   Remove any stale `agent:*` labels; set Project "Agent Delivery Control Plane" Status to `Done`
   (fallback-write only if automation has not projected it).
4. **Update Epic B #3020**: the slice table / status section reflects B1 as delivered+verified
   (with the bifrost PR refs), B2 gate state per ADR-0055 T2/T3 enactment (#3131/#3132), B3
   unchanged.
5. **Update this spec directory** in the same pass (docs PR): `README.md` `State:` line to
   delivered/closed, capability acceptance checklist ticked, relationship-to-GitHub-issues section
   updated — so the spec stops reading as an active pre-delivery lane (feature-breakdown closure
   rule).
6. **Route residuals**: any observation that survives closure (e.g. a deferred UAT nit) becomes a
   BuilderOps `LearningSignal`, a bounded follow-up issue, or an explicit `none` — never a dangling
   to-do in a comment.

## Concretely

```bash
# All GitHub mutations via REST (shared rate-limit discipline):
gh api repos/RasmusTho/agentic-pkm-mvp/issues/3023/comments -f body="Closure ledger: …"
gh api -X PATCH repos/RasmusTho/agentic-pkm-mvp/issues/3023 -f state=closed
gh api -X PATCH repos/RasmusTho/agentic-pkm-mvp/issues/3020 -F body=@updated_epic_body.md
```

## Why This Matters

An open tracking issue over delivered work invites duplicate pickup (it already happened once in
this slice's history: a stale `agent:ready` was removed on 2026-07-06 after work was underway), and
a closed one without a ledger invites false confidence. This task is the difference between "the
agents stopped working on B1" and "B1 is done, and here is the proof."

## Acceptance Criteria

- [ ] Every #3023 AC checkbox is ticked with a named evidence pointer, and the closing comment
  carries the full ledger (bifrost PRs, CI runs, UAT receipt, round-trip receipt). `Verify:` runtime
  receipt — #3023 closed state + closing comment content.
- [ ] #3023 carries no `agent:*` label after closure and its Project Status is `Done`. `Verify:`
  runtime receipt — label list + Project state on #3023.
- [ ] Epic B #3020 body reflects B1 delivered+verified with refs; B2/B3 gating text unchanged in
  meaning. `Verify:` doc writeback at issue #3020 body :: Slices table / Status section.
- [ ] `docs/YGGDRASIL_APP_SHELL_COMPLETION/README.md` `State:` line and acceptance checklist reflect
  closure (docs PR merged). `Verify:` doc writeback at
  `docs/YGGDRASIL_APP_SHELL_COMPLETION/README.md :: State` .
- [ ] Residual observations are routed (LearningSignal / follow-up issue / explicit `none`).
  `Verify:` closing comment names the routing outcome.

## How to Verify (Pre-Merge)

- The docs PR (spec state-line update) passes docs checks; the GitHub mutations are verified by
  re-reading the live issue state via REST after applying them (fail-loud, no assumed success).
- Gate check before starting: receipts for YGGSHELL-04 and YGGSHELL-05 exist on #3023 (spec
  INV-B1C-4). If either is missing, this task stays blocked — do not close on partial evidence.

## Out of Scope

- Closing Epic B #3020 itself (B2/B3 remain).
- Any owner-doc claim that iPhone support is a "supported product surface" beyond what Epic B
  already states — owner-doc promotion beyond the epic is a separate decision at epic closure.
- Re-litigating any delivered slice; defects found post-closure are new bug intake.

## Related Docs

- `docs/YGGDRASIL_APP_SHELL_COMPLETION/README.md` (capability acceptance + INV-B1C-4)
- `.codex/skills/verification-and-closure/SKILL.md`, `.codex/skills/feature-breakdown/SKILL.md`
  (closure reconciliation rules)
- `docs/adr/ADR-0050-cross-repo-governance-and-bifrost-client-repo.md` §1 (hub owns
  tracking/closure)

## Related GitHub Issues

One hub issue (`type:task`, `agent:blocked` until YGGSHELL-01..05 receipts exist), linking #3023 and
#3020. TCD hint: Sonnet / medium effort — judgment-bearing reconciliation but fully scripted
surfaces; no code.
