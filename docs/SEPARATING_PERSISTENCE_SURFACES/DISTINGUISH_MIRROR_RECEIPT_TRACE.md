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

State: Implementation complete. Docs-only. Downstream of SEPSURF-04.

# Distinguishing Mirror, Receipt, Operational Trace, and Index/Projection

## Why this distinction matters

Inside the system surface (task 4), four sub-kinds are particularly easy to collapse into one another in documentation and runtime: **mirrors**, **receipts**, **operational traces**, and **indexes/projections**. When they collapse, the user loses distinct guarantees: portability vs. accountability, human-facing records vs. diagnostic breadcrumbs, durable source-of-truth vs. rebuildable projections.

Two upstream contracts have already separated mirrors, receipts, and traces:
- `MIRROR_RECEIPT_DECISION.md` distinguishes mirrors from receipts
- `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` distinguishes receipts from traces and names audit records as adjacent

This document restates those separations at the persistence-surface level, adds the fourth sub-kind (index/projection), names the hard invariants that define each, and cites cautionary tales (Finding 4 and Finding 5) that demonstrate what the collapses look like in practice. This task does **not** fix the collapses; fixes belong to enabling-change work.

## Mirror

**Identity:** A portable machine-side projection of a human artifact. Mirrors preserve artifact identity, structure, and metadata in a form that survives device changes, repo resets, and rebuilds. Used for continuity, portability, identity repair, and local-first replica convergence.

**Function:** Mirrors answer the question "what does this human artifact look like in projection?" They are the runtime's read-side continuity structure — the answer to "what did I last see for this artifact?"

**What a mirror is:**
- A machine-owned projection of the human artifact
- Portable across instances and devices
- Rebuildable from the original artifact
- A structural memory of "what we remember about this"

**What a mirror is not:**
- A record of what the system did (that is a receipt)
- An audit log (that is an audit record)
- The definition of the artifact (the original note is the definition)

**Upstream contract:** `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`

## Receipt

**Identity:** A human-legible accountability record of what happened, under what authority, on what basis, and with what outcome. Receipts are the machine's answer to "what did the system do on my behalf?" They are meant to be readable by a human who wants to understand and trust the system.

**Function:** Receipts make system action *inspectable*. They answer: Who initiated this? What was the intent? What authority did they have? What happened? What was the outcome? A user reading a receipt should understand what the system did and why.

**What a receipt is:**
- A human-legible accountability surface
- A record of action, authority, basis, and outcome
- The machine's answer to the user's question "what happened?"
- Durable enough to be reviewed later

**What a receipt is not:**
- A portable projection of the artifact (that is a mirror)
- A raw runtime trace (operational traces support receipts but are not themselves receipts)
- An ephemeral log (receipts are meant to persist)

**Upstream contract:** `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` §1

## Operational Trace

**Identity:** Runtime coordination and diagnostic records — the machine's internal breadcrumbs. Traces record outbox events, trace_id-linked logs, orchestration decisions, watcher and worker run records, and similar runtime housekeeping. Traces are for diagnosing what the machine did internally, not for human accountability.

**Function:** Operational traces support runtime diagnostics, replay, and coordination troubleshooting. They help engineers understand what the system tried to do when something failed.

**What an operational trace is:**
- An internal runtime breadcrumb
- Ephemeral (lives long enough for diagnostics, may be cleaned up later)
- For machine operators and engineers to troubleshoot and understand coordination
- Often linked by trace_id or execution context

**What an operational trace is not:**
- A human-legible accountability surface (that is a receipt)
- A durable inspectable record (that is an audit record)
- A source-of-truth for what the user intended

**Upstream contract:** `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` §2

## Audit Record

**Identity:** Durable inspectable records preserved for later review and compliance. Audit records are distinct from operational traces (which are ephemeral) and are often derived from or linked to traces, but they serve a different purpose: providing a legal/compliance trail rather than operational diagnostics.

**Function:** Audit records create an immutable record of significant system actions for later inspection, compliance verification, or regulatory review.

**What an audit record is:**
- A durable record meant to survive long-term
- Often tied to compliance or legal requirements
- Preserved in a form suitable for auditing
- Linked to receipts or traces for context

**What an audit record is not:**
- An operational trace (not ephemeral; not for real-time diagnostics)
- A receipt (not meant to be human-readable; meant for compliance machines)

**Upstream contract:** `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` §3

## Index / Projection

**Identity:** Search-time reconstructed representations of artifacts for retrieval, ranking, scoring, embedding lookup, hybrid-store reads, and context assembly. Indexes and projections are rebuildable derived-state that helps capabilities like retrieval, orientation, and resurfacing find and score material without moving or mutating the artifacts themselves.

**Function:** Indexes answer the question "where is the relevant material?" They support finding, ranking, and contextualizing without requiring the user to know where things are or requiring the artifacts to be transformed.

**What an index/projection is:**
- A rebuildable derived representation
- Created from writing-surface, retention-surface, and system-surface sources
- Meant to be reconstructed when indexes are stale or corrupt
- A way to find and score material efficiently

**What an index/projection is not:**
- The artifact it projects (the original artifact is the artifact)
- A mirror (not a portability/continuity structure; a rebuildable index does not carry identity-repair semantics)
- A receipt or accountability surface (findability is not action; "I found this" ≠ "I did this on your behalf")
- A source-of-truth (must remain safely rebuildable from upstream sources)

**Upstream contract:** Named in this spec (no upstream concept contract yet). Future work may promote index/projection into its own dedicated concept contract, but this persistence-surfaces capability does not require that.

## The Six Hard Invariants

These non-equivalences define the structural line of defense between accountability and logs, between remembering and finding, between system action and derived convenience:

1. **mirror ≠ receipt** — A portability/projection artifact must not carry accountability semantics by accident. Mirror fields (identity, structure, metadata) must not include audit markers or action logs.

2. **receipt ≠ trace** — A human-legible accountability surface must not be replaced by raw runtime breadcrumbs. Receipts are curated and readable; traces are for machines.

3. **trace ≠ audit record** — An ephemeral runtime coordination record is not a durable inspectable record. Traces may be cleaned up; audit records are kept.

4. **index ≠ mirror** — A search-time reconstruction is not a portability projection. Rebuildable indexes do not carry the continuity/identity-repair role of mirrors, and mirrors do not carry retrieval/scoring semantics.

5. **index ≠ receipt** — An index entry is not accountability. The fact that something is findable is not the fact that the system did something inspectable on the user's behalf.

6. **index ≠ source-of-truth** — The index must be safely rebuildable from its upstream sources (writing, retention, and system surfaces). If an index silently becomes the only place a piece of meaning lives, the capability has failed and the cognitive-prosthetic guarantee is broken.

## Cautionary tales (cited for clarity; not fixed here)

Finding 4 and Finding 5 from the v6.0 architecture review are textbook examples of what happens when these invariants fail. They are cited here as cautionary tales to illustrate the cost of collapse; they are **explicitly not in scope** for this capability.

### Finding 4: Mirror conflates artifact identity with audit log

**What happens:** The current `VaultMirror` implementation mixes identity fields (used for portability) with audit markers (used for accountability). Over time, mirror files become read as accountability records. The mirror becomes the master of the note. Users stop trusting the original note and read the mirror as the source of truth.

**Why it happens:** When mirror and audit live in the same data structure, they are easy to conflate. Portability and accountability look like the same problem if you do not name them separately.

**How to spot it:** Mirrors start carrying timestamps of system actions. Mirror reads become the way users understand what the system did. The mirror field becomes "the truth" about the artifact.

**In scope here:** This task names the collapse clearly so readers understand what mirror ≠ receipt means. **Not in scope:** Fixing VaultMirror, prescribing the companion-note migration, or touching runtime code. The fix belongs to enabling-change work.

**Reference:** `docs/plans/V60_ARCHITECTURE_TARGET.md` §Finding 4

### Finding 5: Promotion mutates state without clear transition record

**What happens:** Promotion (moving a note from one zone to another, or marking it as stable/canonical) currently writes state mutations without emitting a distinct receipt. The state change *is* the record of what happened. Users read state as a proxy for action, and accountability dissolves into grep.

**Why it happens:** When receipts are optional and traces are cheap, state mutation looks like a sufficient record. Why write a receipt if the state change itself is evidence?

**How to spot it:** Users need to read code or DB rows to understand what the system did. "What happened to this note?" requires artifact inspection rather than receipt inspection. State and action become indistinguishable.

**In scope here:** This task names the collapse (receipt ≠ trace) clearly so readers understand why promotion needs a distinct accountability surface. **Not in scope:** Fixing promotion flows, prescribing receipt emit patterns, or touching runtime code. The fix belongs to enabling-change work.

**Reference:** `docs/plans/V60_ARCHITECTURE_TARGET.md` §Finding 5

## Bridge to task 6: Classification

All four sub-kinds (mirror, receipt, operational trace, index/projection) live on the system surface. None live on the writing or retention surface. This distinction is the foundation for task 6 (Classify Current Artifacts), which maps every current runtime artifact class (vault note, VaultMirror, companion note, store payload, outbox event, audit row, index record, status callout, etc.) to exactly one surface, with explicit flags for where the companion-note migration leaves pending state.

---

## Purpose (Original Specification Section)

Inside the system surface, the four sub-kinds **mirror**, **receipt**, **operational trace**, and **index/projection** must remain distinct. This task produces the document that names the invariants each sub-kind carries, the collapses that must not happen, and the existing concept contracts each sub-kind is subordinate to. Finding 4 and Finding 5 from the architecture review are cited as cautionary tales that demonstrate what the collapses look like in runtime; this task does **not** fix them.

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
   - **Finding 4 (mirror conflates artifact identity with audit log)** — the current `VaultMirror` implementation mixes identity fields with audit markers. This is the textbook collapse this task is naming. The document cites Finding 4 as the example of what happens when mirror and audit blur; it does **not** prescribe a fix, does **not** touch VaultMirror, and does **not** prescribe the companion-note migration that addresses the underlying collapse. Reference: `V60_ARCHITECTURE_TARGET.md` §Finding 4.
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
