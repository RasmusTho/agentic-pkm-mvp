State: Concept contract (event/intent versioning + compatibility; implementation-agnostic).

# Event/Intent Compatibility Contract — evolvable coordination

## Purpose

Events and intents are durable coordination artifacts: they connect components, preserve auditability, and allow the system to evolve over time.

This contract keeps evolution safe:
- **Old artifacts remain usable** (replay, audit, migration, debugging).
- **New producers do not break old consumers** (forward compatibility).
- **New consumers can still read old histories** (backward compatibility).

The contract governs **meanings and invariants**, not transports, storage engines, or libraries.

## Outbox envelope invariants (conceptual)

All events/intents must be wrapped in a minimal envelope whose semantics are stable over time. Exact field names are non-contractual; the envelope must be able to express:
- **Type identity**: what kind of artifact this is (stable semantic category).
- **Schema/meaning version**: which meaning contract applies.
- **Instance identity**: a stable idempotency key for this specific instance.
- **Source**: who/what emitted it (attribution).
- **Time**: when it was emitted (audit aid; not truth).
- **Payload**: the domain-relevant content.
- **Optional metadata**: non-semantic context that must not change meaning.

Envelope rules (must hold):
1) **Stable semantics beat stable shapes.** Meanings remain stable even if internal representations change.
2) **Append-only evolution.** Compatibility is preserved by adding optional fields or introducing new event types.
3) **Unknown-field tolerance.** Consumers ignore unknown fields; pass-throughs preserve them.
4) **Unknown-type tolerance.** Unknown event types must not crash consumers; they must degrade safely (ignore, record, or route to a generic handler).
5) **Explicitness over inference.** Critical meaning must not depend on field order, implicit defaults, or “magic” interpretation of missing data.

## Versioning rules (high level)

Versioning protects meaning.

A semver-ish model is recommended:
- **Major**: meaning-breaking changes (new interpretation of existing fields, changed idempotency semantics, changed required set).
- **Minor**: additive changes (new optional fields, additional metadata, clarifications).
- **Patch**: non-semantic clarifications (docs, formatting, optional metadata).

Rules:
- **Additive by default.** Prefer new optional fields or new event types.
- **Never silently reinterpret.** Meaning changes require an explicit major boundary.
- **Old meaning remains readable.** New consumers must still interpret old versions under their original meaning.
- **Translations are explicit.** If old → new mapping is needed, it must preserve provenance and be auditable.

## Backward + forward compatibility expectations

### Backward compatibility (new readers, old artifacts)
New consumers must read older artifacts by:
- Treating missing optional fields as **unknown** (not as a new meaning).
- Preserving the meaning of existing fields and type identities.
- Using version signals to select a safe interpretation rather than guessing.

### Forward compatibility (old readers, new artifacts)
Old consumers must handle newer artifacts by:
- Ignoring unknown fields.
- Treating unknown types as **not applicable** rather than as fatal.
- Avoiding durable side effects when required meaning is missing or unrecognized.

Forward compatibility is a safety requirement: evolution must not become “upgrade everything or break”.

## Idempotency + dedupe keys (conceptual guidance)

Consumers must assume at-least-once delivery and must not create duplicate durable effects.

Guidance:
- Every event/intent type must define its **idempotency key** (instance identity): what makes two instances “the same”.
- Prefer an explicit, stable instance id in the envelope.
- If an event/intent can be re-emitted with the same meaning, it must reuse the same idempotency key.
- When a type produces durable effects, consumers must dedupe by the idempotency key before applying effects.

If explicit instance ids are not available, the event contract must define a deterministic dedupe key derived from stable semantic fields (e.g., type identity + subject identity + a stable action identity). Never use volatile data (timestamps, ordering, transient counters) as the dedupe key.

## Checklist: adding a new event/intent type

When introducing a new type, document the contract for it:
- **Meaning**: what concept this type represents (and what it does not represent).
- **Required vs optional**: which payload elements are required to act vs only to display/audit.
- **Idempotency**: the idempotency key definition and re-emission rules.
- **Compatibility story**: how older consumers will ignore it safely; how newer consumers will read older histories.
- **Failure semantics**: what “can’t process” means (ignore, defer, record error) without crashing the system.
- **Boundary posture**: how it respects Domain/Plane/Trust constraints and avoids silent cross-boundary effects.
