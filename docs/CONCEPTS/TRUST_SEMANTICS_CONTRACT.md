State: Concept contract (trust semantics for safety + epistemic hygiene; implementation-agnostic).

# Trust Semantics Contract — assert / suggest / apply

## Purpose

Trust is both **user safety** and **epistemic hygiene**:
- It prevents uncertain, low-provenance, or cross-domain material from being laundered into confident claims.
- It prevents automation from making durable changes without explicit human intent and auditability.

This contract defines how the system must choose and gate three verbs — **ASSERT**, **SUGGEST**, **APPLY** — as a function of provenance trust and boundary context.

This composes with `docs/CONCEPTS/LAYERING_MODEL.md` (Domain/Plane/Trust/Zone) and `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md` (discovery → citation → preview → materialization).

## Trust tiers (conceptual archetypes)

Trust is a provenance- and review-based constraint, not a measure of usefulness. Exact tier names are non-contractual; the semantics below must hold.

Common archetypes (often ordered higher → lower by default):
- **Human-authored, reviewed/confirmed** — explicitly vetted for correctness/intent.
- **Human-authored, raw/unreviewed** — drafts, placeholders, tentative claims.
- **Imported / external** — originates outside the user’s authorship; may be high quality, but is not “confirmed by the user” until reviewed.
- **Machine-proposed / derived** — generated suggestions, summaries, inferred structure, or extracted claims; never authoritative on its own.

Trust can change over time (e.g., after review). Any trust change is a first-class state transition and must be recorded as a **trust delta** (see Receipts).

## Boundary interaction (Domain / Plane / Zone)

Trust never acts alone; it gates behavior within the canonical boundary model:
- **Domain** is the primary scope boundary. Trust does not grant cross-domain permission.
- **Plane** constrains exposure and durability (writing surface vs retention surface vs system plane).
- **Zone** influences prioritization (ranking/attention), not permission.

Rule of thumb: **Zone can reorder; Trust can degrade verbs; Domain/Plane can forbid crossings unless explicitly bridged.**

## The three verbs (contractual semantics)

### ASSERT (present as true)
ASSERT governs what the system may present as true, settled, or reliable.

Constraints:
- **Evidence-required**: assertions must be grounded in sufficiently trusted sources; uncertainty remains visible when evidence is weak, missing, or conflicting.
- **Provenance-preserving**: assertions must not erase source identity; a human can trace “why this is believed” back to inputs.
- **Boundary-aware**: cross-domain assertions require an explicit bridge and must disclose the crossing.

### SUGGEST (propose for consideration)
SUGGEST governs proposals: edits, links, classifications, hypotheses, next steps.

Constraints:
- **Lower bar, higher clarity**: suggestions may be informed by lower-trust material, but must be clearly framed as proposals, not facts.
- **Reversible by default**: accepting/rejecting must be straightforward; suggestions must not “stick” silently.
- **Non-laundering**: machine-proposed content must not be reframed as user-authored truth without explicit adoption.

### APPLY (change/write/do)
APPLY governs durable changes: writing, modifying, moving, materializing, or enacting changes that affect user-facing artifacts or stable system state.

Constraints:
- **Highest bar**: requires explicit human intent (instruction or confirmation) and sufficient trust in the inputs justifying the change.
- **Scoped + accountable**: changes are bounded (what/where/how much) and produce a receipt describing exactly what happened and why.
- **No silent materialization**: content must not be copied into durable surfaces without an explicit APPLY decision.

## Rules for writes (automatic vs confirmed vs never)

The system may write different kinds of artifacts under different conditions.

### May be automatic (default-safe)
Automation may write when all of the following hold:
- The write is **non-semantic** (does not change the user’s meaning or claims).
- The write stays in the **system plane** or other explicitly non-authoritative surfaces.
- The write is **rebuildable** (derived views, caches, indexes, receipts) and does not become the only remaining copy of meaning.

### Requires explicit confirmation (human intent gate)
Confirmation is required when any of the following are true:
- The write changes **writing-surface, human-facing artifacts** (content, titles, durable classifications).
- The action **crosses a domain boundary** (including materialization of retained content into a writing artifact).
- The action upgrades trust (a **trust delta**), or treats external/machine-derived material as confirmed.

### Must never be auto-applied
The system must not auto-apply actions that:
- Create irreversible loss (deletions or destructive overwrites) of user-authored meaning.
- Move or duplicate content across domains in a way that obscures provenance or collapses boundaries.
- Convert low-trust material into asserted truth without explicit review/adoption.

## Evidence + receipt requirements (per verb)

Receipts are required whenever trust gates ASSERT/SUGGEST/APPLY. Receipts are conceptual audit records; their storage location is not specified here.

### ASSERT receipts (what must be recorded)
- The asserted claim (or a stable summary of it).
- The supporting sources and their trust archetypes at time-of-use.
- Boundary context (active domain/plane; whether a bridge was involved).
- Any uncertainty qualifiers (what is unknown, disputed, or inferred).

### SUGGEST receipts (what must be recorded)
- The proposed change/action and its scope.
- The rationale and supporting sources (or “no source / heuristic” when applicable).
- The trust posture (e.g., “suggest-only due to low provenance”).
- The reversal path (how the suggestion can be declined or undone).

### APPLY receipts (what must be recorded)
- The explicit human intent/confirmation that authorized the change.
- The scope of the change and affected artifacts (conceptually).
- Preconditions checked (what had to be true to proceed).
- The sources justifying the change and their trust archetypes.
- Any trust deltas created (what changed, who authorized it).
- Revocability/rollback expectation (how to undo without mutating original sources).

## Human-first posture: inference-first, friction-on-crossing

To keep the system helpful without becoming over-strict:
- **Inference-first**: within the active domain and appropriate plane, prefer SUGGEST over ASSERT when uncertain, and prefer showing sources over making claims.
- **Friction-on-crossing**: increase explicitness (preview/cite → confirm → apply) when crossing domains/planes or when upgrading trust.
- **Conservative on ambiguity**: when boundary or provenance context is missing, degrade to minimal exposure and suggestions rather than assertions or durable writes.
