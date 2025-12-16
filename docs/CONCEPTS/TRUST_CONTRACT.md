State: Concept contract (trust semantics for safety + epistemic hygiene; implementation-agnostic).

# Trust Semantics Contract — assert / suggest / apply

## Purpose

Trust is both **user safety** and **epistemic hygiene**: it prevents the system from laundering uncertain or low-provenance material into confident claims, and it prevents automation from making durable changes without explicit human intent.

This contract defines:
- What “trust” means conceptually (provenance-based tiers).
- The three contractual verbs the system operates under: **ASSERT**, **SUGGEST**, **APPLY**.
- How trust gates retrieval, exposure, and materialization across domains/planes.
- What must be recorded (receipts) whenever trust influences behavior.

This composes with `docs/CONCEPTS/LAYERING_MODEL.md` (Domain/Plane/Trust/Zone) and `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md` (discovery → citation → preview → materialization).

## Trust tiers (conceptual archetypes)

The system classifies information by **provenance and review state**, not by how “useful” it seems. Exact tier names are non-contractual; the semantics below must hold.

Common trust archetypes (ordered from higher to lower, by default):
- **Human-authored, reviewed/confirmed** — authored by the user and explicitly vetted for correctness/intent.
- **Human-authored, raw/unreviewed** — authored by the user but not yet checked (may contain drafts, placeholders, or tentative claims).
- **Imported / external** — originating outside the user’s authorship (documents, messages, feeds, third-party artifacts); may be high-quality, but must not be treated as “confirmed by the user” until reviewed.
- **Machine-proposed / derived** — generated suggestions, summaries, inferred structure, or extracted claims; never treated as authoritative on its own.

Trust may change over time (e.g., when an imported excerpt is reviewed). Any trust change is a first-class state transition and must be recorded as a **trust delta** (see receipts).

## The three verbs (contractual semantics)

### ASSERT (present as true)
ASSERT governs what the system may present as true, settled, or reliable.

Constraints:
- **Evidence-required**: assertions must be grounded in adequately trusted sources; uncertainty must remain visible when evidence is weak or conflicting.
- **Provenance-preserving**: assertions must not erase source identity; a human must be able to trace “why this is believed” back to inputs.
- **Boundary-aware**: assertions must respect domain boundaries; cross-domain assertions require an explicit bridge and must disclose the crossing.

### SUGGEST (propose for consideration)
SUGGEST governs what the system may propose: edits, links, classifications, next steps, hypotheses, or interpretations.

Constraints:
- **Lower bar, higher clarity**: suggestions may be informed by lower-trust material, but must be clearly marked as proposals, not facts.
- **Reversible by default**: accepting/rejecting must be straightforward; suggestions must not “stick” silently.
- **Non-laundering**: machine-proposed content must not be reframed as user-authored truth without explicit adoption.

### APPLY (change/write/do)
APPLY governs what the system may change, write, or enact in durable user-facing artifacts or operational state.

Constraints:
- **Highest bar**: requires explicit human intent (direct instruction or explicit confirmation), plus sufficient trust in the inputs that justify the change.
- **Scoped + accountable**: changes must be bounded (what/where/how much) and must generate a receipt describing exactly what happened and why.
- **No silent materialization**: content must not be copied/rewritten into durable surfaces without an explicit APPLY decision.

## Trust gates (what trust controls)

Trust does not merely “filter results”; it gates *how* information may be used.

### Retrieval ranking vs exposure vs materialization

- **Retrieval ranking**: trust may influence ordering and emphasis, but low-trust material can still be discoverable. Ranking is not permission.
- **Exposure** (what is shown to the human): trust determines how much detail may be revealed and in what mode (cite/preview), especially for sensitive or cross-domain material.
- **Materialization** (turning information into durable artifacts): requires explicit APPLY intent; lower-trust material may be previewed or cited, but must not become durable content without an intentional step that preserves provenance.

### Cross-domain bridges must record trust deltas

When information crosses domains via an explicit bridge:
- The system must record **what crossed** and **why it was allowed**.
- The system must record any **trust delta** implied by the crossing (e.g., “imported” → “reviewed” after human confirmation; or “reviewed in Domain A” does not automatically become “reviewed in Domain B” without explicit re-affirmation).
- The system must never collapse domains by treating a bridge as a full merge; bridges are scoped permissions with explicit, auditable constraints.

### Archive exposure modes (cite / preview / materialize)

When interacting with cold/archive material, trust governs exposure mode:
- **Cite**: reference as evidence while preserving provenance; assertions using citations must respect ASSERT constraints.
- **Preview**: show a bounded excerpt/summary for inspection; previews are views, not durable copies.
- **Materialize**: intentionally create durable, editable artifacts from archive material; requires APPLY intent, preserves provenance, and records the trust delta (what changed from “source” to “user-facing artifact”).

## Receipt requirements (what must be recorded when trust is used)

Whenever trust influences ASSERT/SUGGEST/APPLY, the system must record enough to reconstruct and audit the decision:
- **Verb used**: ASSERT vs SUGGEST vs APPLY.
- **Initiator**: human intent vs automation acting under explicit human intent.
- **Inputs and provenance**: which sources informed the decision, including their trust archetypes at time-of-use.
- **Boundary context**: active domain/plane context and whether a cross-domain bridge was involved.
- **Trust gating outcome**: what was permitted/denied/degraded (e.g., “suggest-only”, “preview-only”, “assertion blocked”, “apply requires confirmation”).
- **Trust deltas**: any changes to trust classification caused by review/adoption/materialization, including who/what authorized the change.
- **Outputs affected**: what was asserted, what was suggested, or what was changed (conceptually), plus revocability/rollback expectations where applicable.
