State: Concept contract (event/intent versioning + compatibility; implementation-agnostic).

# Event/Intent Compatibility Contract — evolvable coordination

## Purpose

Events/intents are durable coordination artifacts: they connect components, preserve auditability, and allow the system to evolve over time. This contract exists to keep evolution safe:
- **Old artifacts remain usable** (replay, audit, migration, debugging).
- **New producers do not break old consumers** (forward compatibility).
- **New consumers can still read old histories** (backward compatibility).

The contract governs **meanings and invariants**, not specific implementations, transports, or libraries.

## Envelope expectations (conceptual)

All events/intents must be wrapped in a minimal **envelope** whose semantics are stable over time. The exact field names are non-contractual; the envelope must be able to express:
- **Type identity**: “what kind of thing this is” (stable semantic category).
- **Instance identity**: “which instance this is” (stable identifier for de-duplication/idempotence).
- **Time**: when it was emitted (for audit and ordering heuristics, not as truth).
- **Source**: who/what emitted it (for attribution and debugging).
- **Version**: which schema/meaning contract applies (for compatibility decisions).
- **Payload**: the domain-relevant content of the event/intent.
- **Optional metadata**: non-semantic context that must not change meaning.

Envelope rules (must hold):
1) **Stable semantics beat stable shapes.** The envelope’s *meaning* must remain stable even if internal representations change.
2) **Idempotence is an expectation.** Consumers must assume at-least-once delivery and must not create duplicate durable effects when the same instance is observed again.
3) **Append-only evolution.** Compatibility is preserved by adding new optional fields or new event types; existing meanings are not silently repurposed.
4) **Unknown-field tolerance.** Consumers must ignore unknown fields and preserve them when acting as pass-throughs; producers must not assume all consumers understand new fields.
5) **Explicitness over inference.** Critical meaning must not depend on field order, implicit defaults, or “magic” interpretation of missing data.

## Compatibility rules (backward + forward)

### Backward compatibility (new readers, old artifacts)
New readers/consumers must be able to interpret older artifacts by:
- Treating absent optional fields as “unknown” (not as a new meaning).
- Preserving the original meaning of existing fields and type identities.
- Using version signals to select safe interpretation rather than guessing.

Breaking changes are allowed only when explicitly versioned as such and paired with a clear migration story (how old histories remain readable and auditable).

### Forward compatibility (old readers, new artifacts)
Old readers/consumers must degrade safely when encountering newer artifacts by:
- Ignoring unknown fields.
- Treating unknown types as “not applicable” rather than as errors that halt the system.
- Avoiding side effects when required meaning is missing or unrecognized.

Forward compatibility is a safety requirement: evolution must not turn into “upgrade everything or break”.

## Versioning strategy (high level)

Versioning exists to protect meaning:
- **Additive changes** (new optional fields, new event types) are the default evolution path.
- **Deprecation is explicit**: old meanings remain valid for a defined period; replacement types/fields are introduced rather than silently repurposing existing ones.
- **Major meaning changes** require explicit version boundaries (so old artifacts can still be interpreted under their original meaning).
- **Bridges/translations** (when needed) must be explicit and auditable: translating old → new must preserve original meaning and provenance.

## What must remain stable

The stable surface is the **meaning contract**:
- What the type identity *means*.
- What each field *means* (including units, scope, and whether it is authoritative vs advisory).
- What idempotence *means* for the artifact (what counts as “the same instance”).
- Which fields are required to act vs required only to display/audit.

Implementations may change freely (storage, routing, internal pipelines) as long as these meanings and invariants remain intact.

## Anti-patterns (contract violations)

- **Breaking semantics under the same version** (e.g., reinterpreting a field without a version boundary).
- **Silent reinterpretation** (changing meaning without leaving an audit trail of the change).
- **Repurposing type identity** (“same type name, different concept”).
- **Non-additive schema changes without compatibility** (removing/renaming fields in a way old consumers can’t tolerate).
- **Treating unknown as false** (unknown fields/types must not be interpreted as “no” or “safe” by default).
