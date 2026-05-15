State: Concept decision (mirror vs receipt separation in service of human function).
Doc role: Core SoT
Authority: Canonical decision on how `Mirror Artifact` and `Receipt Artifact` should be interpreted in current and near-term implementation; adjacent docs may describe current surfaces, but must not collapse the two concepts again.

# Mirror and Receipt Decision

## Purpose

This document records the decision on whether `Mirror Artifact` and `Receipt Artifact` should
remain only an ontological distinction or become distinct first-class implementation concepts.

The broader receipt-vs-trace-vs-audit distinction is clarified in
`docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`.
The primary question is not architectural elegance.
It is which distinct human and cognitive functions the system must serve:
- preserving a stable machine-side projection of human work,
- and making system action understandable, inspectable, and accountable.

## Decision

`Mirror Artifact` and `Receipt Artifact` are now distinct first-class implementation concepts in the
repo's conceptual and runtime-contract language.

This does **not** mean the current runtime already has two fully separated storage subsystems.
It means:
- they must now be described as different kinds of implementation target,
- new docs and runtime changes must preserve the distinction,
- and transitional combined surfaces must be treated as temporary compatibility shapes rather than
  as evidence that the concepts are identical.

## Functional problem being solved

The system must do at least two different kinds of support work for the human:

1. preserve continuity of artifacts across ingest, healing, sync, rebuild, and projection,
2. explain what the system did, why it did it, and under what authority.

These are different functions.

If they are collapsed into one vague "log/mirror" idea, the human loses clarity about:
- what is the portable projection of the artifact,
- what is the accountability record of system action,
- and what operational traces exist only to let the runtime coordinate itself.

## Why this decision is necessary

The current runtime already shows that these concepts serve different purposes:

- `VaultMirror` is used as a portable machine-side projection of vault notes and as an identity /
  healing aid during ingest.
- AI status callouts in notes act as human-facing receipt surfaces for executed actions.
- event streams and audit rows provide operational traces that may support receipts, but are not the
  complete receipt model.
- `app/services/note_log.py` still names a canonical per-note path as a "log", but the actual file
  currently behaves much more like a mirror than a full accountability artifact.

Leaving the concepts merged would keep three different semantics collapsed:
- projection / portability,
- human accountability,
- and operational event trace.

That collapse is now more harmful than helpful.

## Canonical meanings

### `Mirror Artifact`

A mirror artifact is a portable machine-side projection of a human-facing artifact.

Problem solved:
- the system needs to preserve continuity of an artifact even when the human-facing file changes,
  moves, loses metadata, or must be reconstructed.

Primary function:
- keep the artifact projectable, healable, and portable across runtime boundaries.

It is not defined by being human-legible accountability history.

### `Receipt Artifact`

A receipt artifact is a human-legible accountability artifact describing what happened, under what
authority, on what basis, and with what result.

Problem solved:
- the human must be able to understand system action without trusting opaque hidden processes.

Primary function:
- make action, authority, basis, and outcome visible enough for inspection, trust, and correction.

It is not defined by being the machine-side projection of the source artifact.

## Current implementation interpretation

The current runtime should now be read as follows:

### Companion note

The `Companion Note` is the per-note system tracking artifact used for continuity and repair.

It is:
- a first-class system artifact,
- the canonical note-level continuity/repair tracker in the forward line,
- and distinct from both the broader portability concept of `Mirror Artifact` and the human-legible
  accountability concept of `Receipt Artifact`.

It is not:
- the full receipt model,
- or merely a convenience projection/cache.

See `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`.

### VaultMirror (legacy, being replaced)

`System/Metadata/VaultMirror/...` was the previous mirror surface implementation.

It is being replaced by the companion note at `vault/<system_folder>/companions/<uuid>.md` (layout-aware; e.g. `vault/⚙️ System/companions/<uuid>.md`), which provides
the same continuity/identity function with:
- flat UUID-based path instead of directory-preserving path,
- a bounded field set that does not duplicate human-owned metadata (`review_state`, `maturity`),
- an attachment manifest for tracking the full artifact surface,
- and writes routed through KnowledgePort.

Clarifying note:
- `mirror artifact` remains a valid broader portability/projection concept,
- the `companion note` is the concrete per-note system-tracking artifact that implements the
  continuity and repair function previously served by VaultMirror,
- code modules `note_mirror.py` and `note_log.py` are legacy and will be removed.

Clarifying note:
- `mirror artifact` remains the broader portability/projection concept,
- while `companion note` is the narrower per-note system-tracking artifact for identity continuity
  and repair.

See `docs/plans/COMPANION_NOTE_AND_AGENT_CONTEXT_PLAN.md` for the implementation plan.

### AI status callout in notes

The AI status callout is a bounded warm-surface receipt surface.

It is:
- a human convenience surface for receipt visibility,
- a partial `Receipt Artifact` manifestation,
- and intentionally non-authoritative relative to the broader system-plane accountability model.

It is not the same thing as the mirror artifact.

### Outbox events and audit rows

Outbox events and audit rows are operational records.

They:
- support receipt construction,
- provide coordination and observability,
- and remain essential for reconstruction,
- but are not by themselves equivalent to human-legible receipt artifacts.

## Consequences for meaning and implementation

From this point forward:

1. `mirror` language should refer to projection/portability semantics, not generic action history.
2. `receipt` language should refer to accountability semantics, not generic logs or event rows.
3. `VaultMirror` should not be described as if it already were the complete receipt store.
4. A note-local AI status block may surface receipts, but it should be described as a receipt
   surface or overlay, not as the mirror.
5. Event streams should remain explicitly distinct from receipts even when they are used to derive
   or support receipt artifacts.

## Implementation posture

The implementation posture is intentionally conservative:

- We are **not** requiring an immediate code-level split into separate storage backends or tables.
- We **are** requiring new runtime and documentation work to model mirror-targeted concerns and
  receipt-targeted concerns as different concerns.
- Transitional files or paths may still carry mixed information, but that mixture must be treated as
  a temporary implementation compromise, not as canonical design.

## Near-term guidance

Near-term implementation should follow these rules:

### Mirror-oriented writes belong with mirror infrastructure

Examples:
- source reference,
- mirrored frontmatter projection,
- ingest fingerprint,
- healing and continuity metadata,
- projection metadata needed for cold rebuild or sync continuity.

### Receipt-oriented writes belong with receipt/accountability surfaces

Examples:
- action outcome lines,
- authority basis,
- execution result,
- trust delta explanation,
- transition/accountability summaries.

These may be surfaced:
- in system-plane receipt artifacts,
- in bounded warm-surface status overlays,
- or both.

They should not be treated as merely "mirror metadata".

## Decision on `note_log_path`

`app/services/note_log.py` is a legacy module being replaced by `app/services/companion_note.py`.

New code must use companion note terminology and the layout-aware `<system_folder>/companions/<uuid>.md` path (resolved via `get_vault_system_dir_rel()`; see `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`).

This has three implications:
- future refactors may rename or split this boundary,
- new code/docs should avoid using `note_log` or `mirror note` wording when the actual concern is
  the companion-note continuity artifact,
- and the `note_log` / `note_mirror` modules should be removed once the companion note service is
  fully implemented.

## Migration direction

The intended migration direction is:
1. replace `VaultMirror` with companion note as the per-note system-surface artifact,
2. treat AI status / similar human-visible records as receipt surfaces rather than as mirror state,
3. preserve the rule that event streams are not the full receipt model,
4. introduce stricter receipt artifacts in the system plane when the implementation is ready,
5. reduce legacy "log" wording where it hides the mirror/receipt distinction,
6. remove legacy `note_log` / `note_mirror` / `VaultMirror` code and paths as the new boundary
   lands,
7. distinguish the per-note `Companion Note` from the broader `Mirror Artifact` concept where
   portability/projection language still matters,
8. and keep `mirror artifact` as a valid broader concept even though the concrete per-note
   implementation is now the companion note.

See `docs/plans/COMPANION_NOTE_AND_AGENT_CONTEXT_PLAN.md` for the phased implementation plan.
