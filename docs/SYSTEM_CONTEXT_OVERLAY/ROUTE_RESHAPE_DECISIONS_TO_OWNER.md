---
name: Route Reshape Decisions To Owner
description: Owner-gated ADR/decline for the two reshape-routed items (SoS spine-doc naming, DESIGN_PRINCIPLES §9 rewording) — decision record only, no enactment
task_id: SBI-8
source_anchor: "docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md :: §3, §9, §13, §14, §15 (Q2, Q4)"
parent_capability: SYSTEM_CONTEXT_OVERLAY
prerequisites: [SBI-1]
depends_on: [DEFINE_SYSTEM_CONTEXT_OVERLAY.md]
can_parallelize_with: []
---

# Route Reshape Decisions To Owner

> **State — DECIDED (owner, 2026-07-03; recorded 2026-07-04, issue #2840).** The owner chose to
> **act on both** reshape items, so a future pass must **not** re-ask Q2/Q4:
> - **Q2 (SoS doc naming):** RENAME `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` → recorded in
>   **ADR-0041** (Accepted); enactment tracked by follow-up **#2855**.
> - **Q4 (DESIGN_PRINCIPLES §9):** REWORD to volatility-isolation language now → recorded in
>   **ADR-0042** (Accepted); enactment tracked by follow-up **#2856**.
>
> SBI-8 produced the two ADRs and the two follow-up issues; it performed no rename/reword itself.
> Enactment is owned by `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`.

**This task is owner-decision material, not agent-executable implementation. Do not mark it
`agent:ready`. File it (if at all) as `agent:needs-human` and do not pick it up as a normal
implementation slice.** Per audit §13: "No reshape is enacted by this audit. Reshape items exist
only as routed proposals." This task's only deliverable is a decision record (an ADR or an explicit
owner decline) — never the rename or rewording itself.

## Purpose

Audit §13 classifies exactly two items as `Reshape — routed`: renaming
`docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` and rewording
`docs/DESIGN_PRINCIPLES.md :: 9. System-of-Systems Thinking` (which actually describes volatility
isolation, not SoS). Both require
a CES/ADR + owner decision per the binding SBS-reconciliation rule
(precedent: `docs/architecture/runtime-semantics.md :: SBS boundary mapping`) — they must not be
enacted by an audit or by an agent acting on the audit's recommendation alone.

## What This Task Does

Present the owner with the two open questions from audit §15 (reproduced here so this task is
self-sufficient without re-reading the full audit):

- **Q2 — SoS naming.** Keep `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`'s title with SBI-1's overlay
  note (audit's recommendation: zero churn, ambiguity already removed by the overlay note), or
  rename the file via CES/ADR (thirteen referencing docs would need updating)? The audit recommends
  *against* a near-term rename.
- **Q4 — DESIGN_PRINCIPLES §9.** Reword "System-of-Systems Thinking" → volatility-isolation language
  now, or leave it until the next principles revision? Reshape either way — the only question is
  timing.

Once the owner decides (or explicitly declines to decide now, which is itself a valid outcome):

- If the owner chooses to act on either question, open the CES/ADR per
  `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`'s stewardship process — that doc owns
  enactment, not this task. This task stops at "an ADR now exists, is Proposed/Accepted, and names
  the follow-up issue that will perform the rename/reword."
- If the owner declines to act now, record the decline explicitly in this file's own state line (or
  a linked BuilderOps record) so a future pass does not re-ask Q2/Q4 without checking here first.

## Concretely

```bash
ls docs/adr/ | grep -i "system-of-systems\|design-principles-9"   # ADR present if owner chose to act
grep -n "State:" docs/SYSTEM_CONTEXT_OVERLAY/ROUTE_RESHAPE_DECISIONS_TO_OWNER.md   # decline recorded if not
```

## Why This Matters

The audit itself is explicit that renaming a load-bearing doc referenced by thirteen other docs is a
"high-churn reshape with no information gain" if done reflexively (audit §6, term-level note) — the
cost of getting this wrong is not a bug, it is thirteen docs' worth of unnecessary churn plus a
period where in-flight links point at a renamed file. Routing it through CES/ADR is what prevents an
agent from "helpfully" enacting a rename the owner never asked for.

## Acceptance Criteria

- [ ] An ADR exists for Q2 (SoS naming) recording the owner's decision (rename now / keep with
      overlay note / explicit decline to decide), OR this file's state line records an explicit
      owner decline to decide now.
      Verify: doc writeback at `docs/adr/` (new ADR, if the owner acted) OR
      `docs/SYSTEM_CONTEXT_OVERLAY/ROUTE_RESHAPE_DECISIONS_TO_OWNER.md` (state line records decline)
- [ ] An ADR exists for Q4 (`DESIGN_PRINCIPLES.md` §9 rewording) recording the owner's decision
      (reword now / defer to next principles revision / explicit decline), OR this file's state
      line records an explicit owner decline to decide now.
      Verify: doc writeback at `docs/adr/` (new ADR, if the owner acted) OR
      `docs/SYSTEM_CONTEXT_OVERLAY/ROUTE_RESHAPE_DECISIONS_TO_OWNER.md` (state line records decline)
- [ ] No rename or rewording is performed by this task itself — only the decision record.
      Verify: `git diff --stat` for this task's PR shows no changes to
      `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`'s filename or the wording of
      `docs/DESIGN_PRINCIPLES.md :: 9. System-of-Systems Thinking`; any resulting rename/reword
      lands in a separate follow-up issue linked from the ADR

## How to Verify (Pre-Merge)

1. Confirm no file rename occurred: `git status --porcelain docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`
   shows no rename/delete.
2. Confirm no wording change to `docs/DESIGN_PRINCIPLES.md :: 9. System-of-Systems Thinking` landed
   as part of this task (`grep -A5 "^### 9. System-of-Systems Thinking" docs/DESIGN_PRINCIPLES.md`
   matches the pre-task wording).
3. Confirm either two ADRs exist (Proposed or Accepted) or this file's own state line documents an
   explicit decline for each of Q2/Q4 — partial (one decided, one silent) is not acceptable; both
   questions need an explicit answer, even if the answer is "not now."

## Out of Scope

- Performing the rename or reword itself — that is separate follow-up work the ADR must explicitly
  spawn as its own issue, once accepted.
- Any other reshape-classified item — audit §13 names only these two as `Reshape — routed`; no other
  task in this directory should be treated as reshape material.
- The dual-role infrastructure stance (Q3) — explicitly owned by the companion thread
  (`FABLE5_PROMPT_INFRA_DOMAIN_AND_MCP_TOPOLOGY.md`), not this task.

## Related Docs

- `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md :: §3, §9, §13, §15 (Q2, Q4)`
- `docs/architecture/runtime-semantics.md :: SBS boundary mapping` (precedent for the binding
  reconciliation rule)
- `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` (owns any resulting reshape enactment)
- `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`, `docs/DESIGN_PRINCIPLES.md :: 9. System-of-Systems Thinking`

## Related GitHub Issues

If filed at all, file as `agent:needs-human` (decision-dependent), never `agent:ready`. TCD hint:
this is not an implementation slice — it is a decision-support artifact for the owner. No model/
reasoning routing applies until the owner has answered Q2/Q4 and a follow-up implementation issue is
created from the resulting ADR.
