State: Accepted (owner decision, 2026-07-04). Records the decision to reword `docs/DESIGN_PRINCIPLES.md :: 9. System-of-Systems Thinking` to volatility-isolation language now, rather than deferring to a future principles revision. Enactment (the reword itself) is deferred to follow-up issue #2856; this ADR does not perform the reword.
Doc role: Decision record (ADR)
Authority: Authoritative for the *decision* that DESIGN_PRINCIPLES §9's heading and framing mislabel their content and will be reworded to volatility-isolation language, and for the timing (now, not next revision). The principle's substance (layers evolve at independent rates; deliberate, minimal, documented cross-layer coupling) is preserved; this ADR retitles/reframes, it does not add or drop a principle.
Owner: Architecture / CES stewardship
Temporal class: Durable decision (supersede via a new ADR only if reversed; the reword itself is tracked by #2856)
Source of truth: This ADR plus `docs/DESIGN_PRINCIPLES.md` §9 and the 2026-07-03 boundary audit §9.

# ADR-0042: DESIGN_PRINCIPLES §9 mislabels volatility isolation as "System-of-Systems Thinking" — reword now

**Date:** 2026-07-04
**Status:** Accepted

---

## Context

Part of the System Context Overlay capability (parent #2833), task SBI-8 (issue #2840). The
2026-07-03 INCOSE/15288 boundary audit (`docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md`
§9) classified `docs/DESIGN_PRINCIPLES.md :: 9. System-of-Systems Thinking` as a `Reshape — routed`
item. The section heading names "system-of-systems thinking," but its three bullets describe
**volatility isolation** — the principle that interaction, cognition, execution, memory, and
governance must be able to evolve at different rates, with deliberate, minimal, documented
cross-layer coupling. That is a differentiated-rate-of-change / volatility-isolation principle, not
INCOSE system-of-systems thinking (which requires operationally- and managerially-independent
constituents — see the sibling decision ADR-0041 and audit §3). The mislabel is a naming defect, not
a substance defect: the principle itself is sound and stays.

Per audit §13, reshape items are owner-gated and routed through an ADR. The audit framed Q4 as a
timing question only ("reword now vs at the next principles revision — reshape either way"). The
owner chose to **reword now**.

Current §9 text (`docs/DESIGN_PRINCIPLES.md:115`):

> ### 9. System-of-Systems Thinking
> - Yggdrasil should be treated as a system-of-systems, not as one undifferentiated agent runtime.
> - Interaction, cognition, execution, memory, and governance must be able to evolve at different speeds.
> - Cross-layer coupling should be deliberate, minimal, and documented.

## Decision

### 1. §9 will be reworded to volatility-isolation language

The heading "9. System-of-Systems Thinking" and its framing will be reworded to name the principle
it actually states — volatility isolation / independent rates of change (recommended heading:
**"9. Volatility Isolation"**). The three intents are preserved: (i) the system is a modular,
differentiated decomposition rather than one undifferentiated runtime; (ii) layers evolve at
independent rates; (iii) cross-layer coupling is deliberate, minimal, and documented. The
"system-of-systems" phrasing in bullet 1 is replaced with modular/differentiated-decomposition
language consistent with ADR-0041.

### 2. Timing: now

The reword is done as its own near-term work, not deferred to an unscheduled future principles
revision. This is the owner's answer to audit §15 Q4.

### 3. Enactment is a separate follow-up (does not happen in this ADR)

The reword is performed by **follow-up issue #2856** (`agent:ready`, docs lane), whose enactment is
owned by `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`. This ADR records the decision; it
performs no wording change. The principle's number (§9) is kept stable to avoid churn in anything
that cites the number.

## Constraints honored

- Decision record only. No wording change to `docs/DESIGN_PRINCIPLES.md` §9 lands in this ADR's PR
  (verified: SBI-8's PR shows the pre-task §9 wording unchanged).
- No principle is added or removed — §9's substance is preserved, only its name/framing changes.
- Settles Q4 only; the SoS doc rename (Q2) is the sibling decision ADR-0041.

## Consequences

- A follow-up issue (#2856, `agent:ready`, `prio:high`, docs lane) now exists to perform the reword.
- DESIGN_PRINCIPLES §9 stops mislabeling volatility isolation as system-of-systems thinking, closing
  the last of the two `Reshape — routed` items from the boundary audit.

## When to revisit

Supersede with a new ADR only if the decision is reversed before #2856 lands, or if a later
principles restructuring renumbers/merges §9.

## References

- Issue #2840 (SBI-8, Q4) — owner-gated reshape decision; owner decision comment recorded 2026-07-03.
- Follow-up issue #2856 — enact the §9 reword.
- `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md` §9, §13, §15 (Q4).
- `docs/DESIGN_PRINCIPLES.md` §9 (the section being reworded).
- `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` — owns reshape enactment.
- ADR-0041 — the sibling Q2 reshape decision (SoS doc rename).
