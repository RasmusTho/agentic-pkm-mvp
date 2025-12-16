State: Concept contract (archive brain exposure + safety; implementation-agnostic).

# Archive Exposure Contract — discovery to materialization

## Purpose

The cold “archive brain” is first-class: it should be searchable and useful. It must also be safe: archive material often contains sensitive, high-volume, or low-trust content. This contract defines how archive content may be exposed into human workflows without accidental leakage, silent copying, or loss of provenance.

This contract composes with the boundary model in `docs/CONCEPTS/LAYERING_MODEL.md` (Domain / Plane / Trust / Zone).

## Exposure Modes (conceptual)

- **Discovery** — identifying potentially relevant archive items (e.g., listing or ranking candidates).
- **Citation** — referencing an archive item as evidence for a claim or output, preserving provenance.
- **Preview** — showing a bounded excerpt or summary of an archive item for human inspection.
- **Materialization** — intentionally turning archive material into a warm, human-editable artifact (e.g., a note, excerpt, or curated synthesis).

These are distinct modes with distinct safety requirements; “preview” must not quietly become “materialization”.

## Contract Rules (must hold)

1) **Cold objects are canonical; indexes are rebuildable.** The archive remains the source of truth; any derived representations are disposable and must not become the only remaining copy of meaning.
2) **Domain + Trust gate exposure.** Exposure decisions must respect domain boundaries and provenance/trust constraints; default behavior must prevent cross-domain leakage.
3) **Discovery is minimal by default.** Discovery should reveal only what is necessary to decide relevance; deeper exposure requires an explicit user step.
4) **Citation must preserve provenance.** When archive material supports an output or claim, the system must keep a stable reference back to the original archive source and avoid laundering it into unattributed text.
5) **Preview is bounded and non-destructive.** Previews are “views”, not copies: they must not silently duplicate sensitive content into the warm surface, logs, or other domains.
6) **Materialization requires explicit intent.** Turning archive material into warm artifacts must be an explicit human choice, recorded as such, and reversible without altering the archive source.
7) **Trust constrains assertions and edits.** Lower-trust archive material may inform suggestions, but durable edits and factual assertions require adequate evidence and (when appropriate) explicit human confirmation.
8) **No implicit boundary crossing.** If domain, trust, or plane context is missing or ambiguous, the system must behave conservatively: avoid exposure beyond minimal discovery and prefer asking for explicit intent.
9) **Cross-domain use must be explainable.** When archive material crosses domains, the system must make the crossing visible (what crossed, why, and under what constraints) and support audit.
10) **Zone influences rank, not access.** Salience (zone) may change what is shown first, but it must not override domain, plane, or trust boundaries.

## Receipt Requirements (what must be recorded)

When exposure occurs (in any mode), the system must record enough to reconstruct and audit the decision without relying on memory or hidden state:
- **Who/what initiated it** (human intent vs automation acting under explicit human intent).
- **Context** (active domain, relevant trust constraints, and whether any cross-domain bridge was in effect).
- **Source identity and provenance** (what archive item was involved, and where it came from).
- **Exposure mode** (discovery vs citation vs preview vs materialization).
- **Scope of exposure** (what was shown or used, and at what level of detail).
- **Transformations** (summarized, excerpted, redacted, aggregated) without losing traceability to the source.
- **Outputs affected** (what new artifacts were created or what existing artifacts were modified, conceptually).
- **Time and revocability** (when it happened, and how the exposure can be withdrawn without mutating the archive source).

