State: New — transcribes the already-settled 20-axis requirements-coverage table from the
2026-07-03 INCOSE boundary audit. Decides nothing new; is an index, not a requirements document.
Doc role: Reference
Authority: Thin index mapping the twenty SRS/requirements axes the audit checked to their verdict
(Well-specified / Scattered / Absent) and current owner doc(s). Does not itself define or own any
requirement — each row's "Home(s)" doc remains the authority for that axis. Where this index and an
owner doc appear to differ, the owner doc wins.
Owner: Architecture spine (docs/SYSTEM_CONTEXT_OVERLAY spec directory, task SBI-5)
Temporal class: strategic
Review cadence: event-driven
Source of truth: docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md §8, §15
Last reviewed: 2026-07-03
Last verified against: docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md §8, §15 (Q1, Q5)

# Requirements Coverage Index (SRS Axes)

## Purpose

No document in this repo self-identifies as a requirements baseline (repo-wide grep, zero hits,
per the 2026-07-03 INCOSE boundary audit). This index closes that gap the minimal way: it maps the
twenty requirement axes the audit checked against ISO/IEC/IEEE 15288-style SRS coverage to their
verdict and current owner doc(s), so a reader can find "where do I go for X" without re-deriving it
from scattered sources. It is not itself a Software Requirements Specification.

## Scope

- The 20-axis coverage table below, reproduced from
  `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md` §8.
- One sentence resolving audit §15 Q1 (scale/perf-budget silence).
- A note on the still-open audit §15 Q5 decision (this index's own placement).

## Out of Scope

- Drafting a full SRS or NFR targets. This is an index over existing docs, not a new requirements
  document (audit §8: "Recommended revisions (not an SRS draft)").
- Answering audit §15 Q1 on the owner's behalf if genuinely undecided — see the note below instead
  of a silent claim that NFRs exist.
- Any other Wave-B or audit-backlog item not named in
  `docs/SYSTEM_CONTEXT_OVERLAY/INDEX_REQUIREMENTS_COVERAGE.md` (task SBI-5).

## Related Docs

- `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md` — source audit (§8, §15).
- `docs/architecture/system-context-overlay.md` — 15288 vocabulary overlay (SBI-1); this index uses
  its terms (System of Interest, enabling system, etc.) rather than redefining them.
- `docs/architecture/traceability-matrix.md` — traces eighteen *doctrine* rows (invariants), a
  different axis set than the requirements axes indexed here; do not conflate the two.
- `docs/DOCS_INDEX.md` — general doc routing map; this index is requirements-axis-specific.
- `docs/ARCHITECTURE.md` — architecture SoT; several axis rows below point here.

## Reading Order

- Start with the axis row for the topic you need, then follow its "Home(s)" doc(s).
- For document-role routing generally (not requirements-specific), use `docs/DOCS_INDEX.md` first.

## Normative Content

### 20-axis coverage table

Verdicts: **W** = Well-specified, **S** = Scattered (exists but no single consolidating owner),
**A** = Absent (no doc covers it today).

| Axis | Verdict | Home(s) |
| --- | --- | --- |
| Mission | W | `docs/PROJECT_KERNEL.md` (lines 9-11); `docs/COGNITIVE_PROSTHESIS_CHARTER.md` §1 |
| Purpose | W | `docs/COGNITIVE_PROSTHESIS_CHARTER.md` §§1-2; `docs/HUMAN-FLOWS.md` |
| Stakeholder needs | W | `docs/CONCEPTS/USER_NEEDS_MODEL.md`; `docs/PROJECT_KERNEL.md` §2 |
| System objectives | W | `docs/PROJECT_KERNEL.md` §3; `docs/foundation/yggdrasil-architecture-context-packet.md` |
| Operational concept | S | Split across `docs/ARCHITECTURE.md`, `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`, `docs/STATUS.md` — no single ConOps owner |
| System context | W | `docs/ARCHITECTURE.md` (lines 95-110); `docs/architecture/system-context-overlay.md` (15288 vocabulary, SBI-1) |
| Functional requirements | S | `docs/HUMAN-FLOWS.md` + `docs/CORE_CONTRACT.md` + `docs/COGNITIVE_PROSTHESIS_CHARTER.md` — no consolidating surface |
| Non-functional requirements | A | Fitness functions exist (`docs/ARCHITECTURE.md`, lines 144-148); no NFR targets are recorded anywhere. See scale/perf note below |
| Architectural constraints | W | `docs/ARCHITECTURE.md` (lines 107-110); `docs/DESIGN_PRINCIPLES.md`; `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` |
| Design principles | W | `docs/DESIGN_PRINCIPLES.md` (eleven principles: 1, 2, 2A, 2B, 3-9) |
| Assumptions | S | Strewn across security docs (`docs/SECURITY_ARCHITECTURE.md` and siblings), `docs/foundation/00-yggdrasil-doctrine.md`, ADRs |
| External interfaces | W | `docs/INTEGRATION_FABRIC_CONTRACT.md` |
| Supporting systems | S | `docs/DEPENDENCIES.md`, `docs/ENVIRONMENTS.md`, compose config — see the audit §2 classification gap |
| Quality attributes | S | Fitness rules, `docs/testing/invariant-tests.md`, security docs — no single quality-attribute register |
| Verification strategy | W | `Verify:` convention (`docs/development/DEV_WORKFLOW.md`, lines 224-270; `.codex/skills/_shared/ISSUE_CONTRACT.md`, lines 53-72); `docs/TESTING.md` |
| Lifecycle | W | `docs/ENVIRONMENTS.md`; `docs/RELEASE_CHANNELS/README.md`; `docs/OPERATIONS.md` |
| Maintainability | S | CES practice + `docs/DESIGN_PRINCIPLES.md` — framed as stewardship, never stated as a requirement |
| Scalability | A | Single-user scope statements exist (e.g. `docs/ARCHITECTURE.md`, line 404); no doc states the omission of scale/perf budgets is deliberate. See note below |
| Knowledge preservation | W | `docs/adr/ADR-0017-*.md`; SBS Human Knowledge Authority (HKA) role; `docs/OPERATIONS.md` recovery section |
| AI governance | W | `docs/AGENT-FLOWS.md`; `docs/adr/ADR-0019-*.md`; `docs/guardrails.md` |

### Scale/perf-budget note (audit §15 Q1)

Scale/perf budgets are deliberately absent by single-user design: Yggdrasil targets one human
operator at local-vault scale, not concurrent-user throughput or multi-tenant latency SLAs
(`docs/ARCHITECTURE.md` line 404 and its neighboring single-user scope statements). This is a
choice, not an oversight — fitness functions exist to check structural properties, but they have no
quantitative NFR targets to check against because none are believed necessary at this scale.

**Q1 is still formally open** (audit §15): the owner has not yet chosen between (a) adopting a
minimal NFR section with concrete latency/availability/durability targets for the prosthesis loop,
or (b) recording this deliberate-absence framing as the final answer. This note records the default
framing per the audit's guidance so the silence stops reading as an oversight; it does not close
Q1. If the owner later adopts option (a), update the "Non-functional requirements" and "Scalability"
rows above accordingly.

### Index placement note (audit §15 Q5)

Q5 (SRS index home: separate index vs. a `docs/DOCS_INDEX.md` section vs. extending the
traceability matrix) was open at audit time. This document exists at
`docs/REQUIREMENTS_INDEX.md` per the audit's own recommendation — a separate thin index, since the
traceability matrix deliberately traces doctrine rather than requirements, and `DOCS_INDEX.md` was
recently slimmed (#2830). If the owner later decides differently, migrate this table to the chosen
location and redirect this path.

## Change Notes

Created 2026-07-03 (SBI-5, #2839) from the 2026-07-03 INCOSE boundary audit §8 table. Q1 and Q5
remain open owner decisions; this document records the audit's recommended defaults for both rather
than blocking on them.

## Writing Guidance

This document is a Reference index, not Core SoT. It explains where requirements coverage lives; it
does not define or own any requirement itself. Update it when an axis's owner doc changes, not when
the underlying requirement changes (that belongs in the owner doc).
