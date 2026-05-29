---
name: Distinguish Mirror, Receipt, Trace, and Index/Projection
description: Separate the four system-surface sub-kinds (mirror, receipt, operational trace, index/projection) with stable invariants; cite Finding 4 and Finding 5 as cautionary tales only
task_id: SEPSURF-05
source_anchor: docs/plans/V60_ARCHITECTURE_TARGET.md :: Delta 9, Finding 4, Finding 5; docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md; docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md
parent_capability: Separating Persistence Surfaces
prerequisites: [SEPSURF-01, SEPSURF-02, SEPSURF-03, SEPSURF-04]
depends_on: [NAME_THE_THREE_PERSISTENCE_SURFACES.md, DEFINE_SYSTEM_SURFACE_CONTRACT.md]
can_parallelize_with: []
---

State: Specification ready. Docs-only. Downstream of SEPSURF-04.

# Distinguish Mirror, Receipt, Trace, and Index/Projection

## Purpose

Inside the system surface, the four sub-kinds **mirror**, **receipt**, **operational trace**, and **index/projection** must remain distinct. This task produces the document that names the invariants each sub-kind carries, the collapses that must not happen, and the existing concept contracts each sub-kind is subordinate to. Finding 4 and Finding 5 from the architecture review are cited as cautionary tales that demonstrate what the collapses look like in runtime; this task does **not** fix them.

## What This Task Does

Produces a single document whose body contains:

1. **Framing.** The system surface (task 4) holds several kinds of support structures. Four of them are particularly easy to collapse into one another in both documentation and runtime implementation: mirrors, receipts, operational traces, and index/projection artifacts. `MIRROR_RECEIPT_DECISION.md` and `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` have already separated the first three concepts; the index/projection sub-kind is named here in the language of persistence surfaces because no upstream concept contract owns it yet. This document restates the separations and names the invariants.
2. **Mirror.** Identity (portable machine-side projection of a human artifact used for continuity, identity, portability, and rebuild), function, and the rule that a mirror is not defined by being a record of *what the system did* — only of *what the human artifact looks like in projection*. Cite `MIRROR_RECEIPT_DECISION.md`.
3. **Receipt.** Identity (human-legible accountability record of what happened, under what authority, on what basis, with what outcome), function, and the rule that a receipt is not defined by being a portable projection of the artifact — it is defined by making action inspectable. Cite `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` §1.
4. **Operational trace.** Identity (runtime coordination/diagnostic record: outbox events, trace_id-linked logs, orchestration traces, watcher and worker run records), function, and the rule that operational traces *support* receipts but are not themselves receipts. Cite `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` §2.
5. **Index/projection.** Identity (search-time reconstructed representation of artifacts for retrieval, ranking, scoring, embedding lookup, hybrid-store reads, and context assembly). Function: rebuildable derived-state that lets capabilities like retrieval, orientation, and resurfacing find and score material without the artifacts themselves being moved or mutated. The rule: an index/projection must never become the artifact it projects. It is read-through, not source-of-truth. It must remain **rebuildable** from the writing, retention, and system-surface sources it projects — if it ever stops being rebuildable, the capability has failed. No upstream concept contract currently owns this sub-kind explicitly; this spec is where it is named. Future work may promote it into its own concept contract, but this capability does not require that.
6. **The six stable non-equivalences (hard invariants).**
   - **mirror ≠ receipt** — a portability/projection artifact must not carry accountability semantics by accident.
   - **receipt ≠ trace** — a human-legible accountability surface must not be replaced by a raw runtime breadcrumb.
   - **trace ≠ audit record** — an ephemeral runtime coordination record is not a durable inspectable record.
   - **index ≠ mirror** — a search-time reconstruction is not a portability projection; a rebuildable index does not carry the continuity/identity-repair role of a mirror, and a mirror does not carry retrieval/scoring semantics.
   - **index ≠ receipt** — an index entry is not accountability; the fact that something is findable is not the fact that the system did something inspectable on the user's behalf.
   - **index ≠ source-of-truth** — the index must be safely rebuildable from its upstream surfaces; if the index silently becomes the only place a piece of meaning lives, the capability has failed.
   These invariants must be stated as strong rules with forward references to the upstream contracts (for mirror/receipt/trace) and to this spec (for index).
7. **Cautionary tales (reference only, do not fix).**
   - **Finding 4 (mirror conflates artifact identity with audit log)** — the legacy `VaultMirror` implementation (deprecated; replaced by companion notes) mixed identity fields with audit markers. This is the textbook collapse this task is naming. The document cites Finding 4 as the example of what happens when mirror and audit blur; it does **not** prescribe a fix, does **not** touch VaultMirror, and does **not** prescribe the companion-note migration that addresses the underlying collapse. Reference: `V60_ARCHITECTURE_TARGET.md` §Finding 4.
   - **Finding 5 (promotion mutates artifact state without a clear transition record)** — promotion currently writes state mutations without emitting a distinct receipt, which is the textbook collapse of "trace as receipt." The document cites Finding 5 as the example of what happens when receipts are implicit in state changes; it does **not** prescribe a fix. Reference: `V60_ARCHITECTURE_TARGET.md` §Finding 5.
   The document must be explicit: these are *cautionary tales referenced for clarity*, not work items owned by this capability. The fixes belong to enabling-change work.
8. **Audit records (optional note).** The document may briefly note that audit records are an adjacent kind that can be derived from traces and can support receipts but is distinct from all four named sub-kinds. This is consistent with `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` §3 and should be referenced, not redefined.
9. **Relation to surface classification.** All four sub-kinds live on the system surface (task 4). None of them lives on the writing or retention surface. This is the bridge to task 6 (classification).

## Concretely

Expected structure:

```
# Distinguishing Mirror, Receipt, Operational Trace, and Index/Projection

## Why this distinction matters
[Four easily-collapsed sub-kinds of the system surface.]

## Mirror
- Identity: portable machine-side projection
- Function: continuity, portability, rebuild, identity repair
- Upstream contract: MIRROR_RECEIPT_DECISION.md
- Is not: a record of what the system did

## Receipt
- Identity: human-legible accountability record
- Function: make action / authority / basis / outcome inspectable
- Upstream contract: RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md §1
- Is not: a portable projection of the artifact

## Operational trace
- Identity: runtime coordination/diagnostic record
- Function: support coordination, diagnosis, replay
- Upstream contract: RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md §2
- Is not: a human-legible accountability surface

## Index / projection
- Identity: search-time reconstructed representation of artifacts
- Function: rebuildable derived-state for retrieval, ranking, scoring,
  embedding lookup, hybrid-store reads, context assembly
- Upstream contract: named here (no upstream concept contract yet)
- Is not: the artifact it projects; is not accountability;
  is not a source-of-truth; must remain rebuildable from upstream surfaces

## Hard invariants
- mirror ≠ receipt
- receipt ≠ trace
- trace ≠ audit record
- index ≠ mirror
- index ≠ receipt
- index ≠ source-of-truth

## Cautionary tales (referenced only, not fixed)
- Finding 4: mirror conflates identity with audit log.
- Finding 5: promotion mutates state without clear transition record.
[Both cited as examples of the collapse this task names.
  Neither is resolved by this task.]

## Audit records (brief note)
[Optional: adjacent kind beyond the four. Refer to contract, do not redefine.]

## Bridge to classification
[All four live on the system surface. Task 6 maps
  concrete runtime artifacts to a single surface each.]
```

## Why This Matters

The six non-equivalences above are the structural line of defense between "the system is accountable" and "the system has logs," and between "the system remembers" and "the system can find again." If a mirror absorbs receipt semantics, the user starts reading mirror files as the record of what the system did, and the mirror silently becomes more authoritative than the human note it projects. If a receipt collapses into an operational trace, accountability becomes a grep exercise. If an index silently becomes the source-of-truth, the user's meaning starts living in a rebuildable projection instead of in the artifacts it projects — the textbook collapse V60 §Delta 3 and §Pillar 3 warn about. Finding 4 and Finding 5 are what the first two collapses look like in the current runtime, which is why they belong as cautionary tales in this document — they show the reader exactly what the invariants exist to prevent.

This task also bridges tasks 1–4 and task 6: by establishing the four sub-kinds explicitly, it gives `CLASSIFY_CURRENT_ARTIFACTS.md` unambiguous labels to attach to each runtime artifact class.

## Acceptance Criteria

- [ ] The document names mirror, receipt, operational trace, and index/projection as distinct system-surface sub-kinds with stable identities.
- [ ] Each sub-kind has an explicit "is" and "is not" framing.
- [ ] Each sub-kind cites the upstream concept contract (`MIRROR_RECEIPT_DECISION.md` for mirror, `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` for receipt and trace). The index/projection sub-kind is named in this spec because no upstream concept contract owns it yet; the spec explicitly acknowledges that promoting index/projection into its own concept contract is future work.
- [ ] The six hard invariants (mirror ≠ receipt, receipt ≠ trace, trace ≠ audit record, index ≠ mirror, index ≠ receipt, index ≠ source-of-truth) are stated clearly and prominently.
- [ ] The index/projection sub-kind explicitly carries the rebuildability rule: it must remain rebuildable from the writing, retention, and system-surface sources it projects, and must never silently become a source-of-truth.
- [ ] Finding 4 is cited as a cautionary tale, explicitly not fixed here.
- [ ] Finding 5 is cited as a cautionary tale, explicitly not fixed here.
- [ ] The document does not prescribe VaultMirror changes.
- [ ] The document does not prescribe promotion-flow changes.
- [ ] The document does not prescribe companion-note implementation shape.
- [ ] The document does not redefine anything the upstream concept contracts already define.
- [ ] A short bridge to task 6 (classification) is present.

## How to Verify (Pre-Merge)

- Read `MIRROR_RECEIPT_DECISION.md` and `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` side-by-side with this document. Confirm every cited definition is consistent with its upstream source.
- Grep for words that would indicate fixing Finding 4 or Finding 5 ("fix", "replace", "emit", "rewrite", "introduce receipt"). These should not appear as prescriptive actions in the body of the document.
- Confirm the six non-equivalence statements are present and visually prominent.
- Confirm the bridge paragraph to task 6 is present.
- Diff the branch and confirm no file outside `docs/SEPARATING_PERSISTENCE_SURFACES/` is touched.

## Out of Scope

- Fixing Finding 4 (mirror conflates identity with audit log).
- Fixing Finding 5 (promotion mutates state without transition record).
- Touching VaultMirror code or docs.
- Touching promotion code or docs.
- Prescribing companion-note migration shape or sequencing.
- Redefining mirror, receipt, trace, or audit record in ways that diverge from upstream concept contracts.
- Classifying concrete runtime artifacts (task 6).
- Designing event payloads, receipt storage, or trace schema.
- Designing UI for accountability.

## Related Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 10, §Delta 9, §Finding 4, §Finding 5
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` (cited as reference, not prescribed)

## Related GitHub Issues

When implementing, a single issue is sufficient: "Implements SEPARATING_PERSISTENCE_SURFACES/DISTINGUISH_MIRROR_RECEIPT_TRACE". The issue body must flag that Finding 4 and Finding 5 are cited as cautionary tales and explicitly not in scope.

---

**Status:** Specification ready. Blocked on SEPSURF-04 merge.
