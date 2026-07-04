State: Accepted (owner decision, 2026-07-04). Records the decision to rename `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` to an accurate title. Enactment (the rename itself plus updating the 27 referencing docs) is deferred to follow-up issue #2855; this ADR does not perform the rename.
Doc role: Decision record (ADR)
Authority: Authoritative for the *decision* that the doc currently named `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` is misnamed under ISO/IEC/IEEE 15288 / INCOSE terms and will be renamed, and for the naming criteria and recommended target name. The doc's architectural *content* (the modular subsystem spine, volatility isolation, authority separation) is unchanged and remains owned by that doc; this ADR renames the container, it does not redefine the architecture.
Owner: Architecture / CES stewardship
Temporal class: Durable decision (supersede via a new ADR only if the rename is reversed; the mechanical enactment is tracked by #2855, not by editing this ADR)
Source of truth: This ADR plus the `docs/architecture/system-context-overlay.md` System-of-Systems glossary framing (SBI-1) and the 2026-07-03 boundary audit §3.

# ADR-0041: `SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` is misnamed — rename to an accurate title

**Date:** 2026-07-04
**Status:** Accepted

---

## Context

Part of the System Context Overlay capability (parent #2833), task SBI-8 (issue #2840). The
2026-07-03 INCOSE/15288 boundary audit (`docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md`
§3) classified the title of `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` as a `Reshape — routed` item:
the file's title asserts a "system of systems," but what the document actually describes is a
**modular, authority-separated single system with volatility isolation** — an internal decomposition
(the 8-subsystem spine) that fails every INCOSE SoS taxon's operational- and managerial-independence
test. The one INCOSE-defensible SoS reading is the operator's *assembled environment*
(Yggdrasil + Obsidian + iCloud, `docs/ARCHITECTURE.md:198`), which this document is not about.

SBI-1 already added a `System of Systems` glossary entry and a one-paragraph overlay note to the
file (`docs/architecture/system-context-overlay.md`, `docs/GLOSSARY.md`) that removes the ambiguity
*in place*. The audit therefore recommended **against** a near-term rename, noting it as
"high-churn, low information gain." The owner reviewed that recommendation and chose to rename
anyway: the in-place note documents the mismatch but leaves a load-bearing, frequently-cited doc
carrying a title that actively misdescribes it, and the owner judged the one-time churn worth an
accurate name. Reshape items are owner-gated and must be routed through an ADR, never enacted by an
audit or by an agent acting on the audit's recommendation alone (audit §13).

Reference-surface reality: the old name is referenced by **27 docs** (`grep -rl
SYSTEM_OF_SYSTEMS_ARCHITECTURE docs/` on 2026-07-04) — more than the audit's ~13 estimate, which
sharpens the "get the enactment right" concern but does not change the decision.

## Decision

### 1. The file will be renamed to an accurate title

`docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` will be renamed. The document describes modular subsystem
architecture with volatility isolation, so the recommended target name is
**`docs/MODULAR_ARCHITECTURE.md`** (final string confirmable at enactment against the
reference-update mechanics — the requirement is that the name describe modular / volatility-isolated
single-system architecture, not "system of systems"). The document's content and its internal
claims are **not** changed by this decision — only the container name.

### 2. Enactment is a separate, mechanical follow-up (does not happen in this ADR)

The rename itself and the update of all 27 referencing docs (including `docs/DOCS_INDEX.md`, the
SBI-1 overlay note, the SBI-3 spine crosswalk, and the `docs/GLOSSARY.md` System-of-Systems entry
link) are performed by **follow-up issue #2855**, whose enactment is owned by
`docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`. This ADR records the decision and authorizes the
follow-up; it performs no rename.

### 3. The glossary/overlay note stays

SBI-1's glossary entry and overlay note remain valid and are updated (not deleted) by #2855 to point
at the new filename. The colloquial "system of systems" usage and the operator-assembled-environment
SoS reading are documentation facts, independent of this file's name.

## Constraints honored

- Decision record only. No file rename, no reference edits, and no wording change land in this ADR's
  PR (verified: SBI-8's PR touches no reference to the old path except this ADR's own prose).
- The architecture the doc describes is not redefined — this is a container rename.
- The one Reshape item this ADR settles is Q2 only; Q4 (`DESIGN_PRINCIPLES.md` §9 reword) is a
  separate decision recorded in ADR-0042.

## Consequences

- A follow-up issue (#2855, `agent:ready`, docs lane) now exists to perform the rename and fix the
  27 referencing docs. Until it lands, the old filename remains in use with SBI-1's in-place note.
- Future contributors get a doc whose name matches its content; the 15288/INCOSE mismatch stops
  being a recurring re-derivation.
- One-time churn across 27 docs plus a window where any in-flight branch referencing the old path
  must rebase — accepted as the cost of the rename.

## When to revisit

Supersede with a new ADR only if the rename decision is reversed before #2855 lands, or if the
document is split/merged such that "the SoS doc" no longer maps to one file.

## References

- Issue #2840 (SBI-8, Q2) — owner-gated reshape decision; owner decision comment recorded 2026-07-03.
- Follow-up issue #2855 — enact the rename + reference updates.
- `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md` §3, §13, §15 (Q2).
- `docs/architecture/system-context-overlay.md` (SBI-1 overlay note + SoS framing),
  `docs/GLOSSARY.md :: System of Systems`.
- `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` — owns reshape enactment.
- ADR-0042 — the sibling Q4 reshape decision (`DESIGN_PRINCIPLES.md` §9 reword).
