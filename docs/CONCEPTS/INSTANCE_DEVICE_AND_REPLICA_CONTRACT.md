State: Concept contract companion (instance, device, replica, and provenance semantics; local-first and eventual-consistency aware).

# Instance, Device, and Replica Contract

## Purpose

This document clarifies the semantic layer underneath local-first multi-device use.

It exists to answer:
- what an `instance` is,
- how a `device` relates to an instance,
- what a `replica` means in a local-first system,
- and how instance provenance should be understood without turning operational plumbing into the
  whole ontology.

This document is subordinate to:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/PROJECT_KERNEL.md`
- `docs/HUMAN-FLOWS.md`

It is upstream of:
- `docs/ARCHITECTURE.md`
- `docs/plans/PROTOCOL_SATELLITE_SYNC.md`
- future sync, replica, and provenance design.

## Core rule

The artifact is primary.
Instances and replicas describe where and how that artifact is presently carried, represented, or
acted on.

Therefore:
- the same artifact may exist across several instances and replicas,
- instance provenance matters,
- but instance identity must not be mistaken for artifact identity.

## 1. Instance

An instance is one local runtime context of the system for the same human.

Problem solved:
- the system may be used from home, work, travel, or satellite setups,
- and each local runtime needs a way to be identified in provenance, sync, accountability, and
  rebuild flows.

An instance may differ in:
- device role,
- available stores,
- local capabilities,
- available artifacts,
- or current synchronization state.

An instance is not the human.
It is also not a separate ontology of artifacts.

## 2. Device role

A device role is the practical posture a device/instance combination has in the broader system.

Examples:
- primary workstation,
- home master,
- work satellite,
- travel/lightweight device,
- partial or narrow-scope instance.

Problem solved:
- not every device should be forced into identical capability or storage assumptions,
- and asymmetry should be intelligible rather than treated as failure.

Device role is therefore about practical participation, not about artifact identity.

## 3. Replica

A replica is a local carried copy or representation of an artifact or derived layer on a particular
instance.

Problem solved:
- local-first systems do not assume one always-current central runtime view,
- and the same artifact may exist in several places with lag, partial visibility, or incomplete
  derived state.

A replica may be:
- complete or partial,
- current or lagging,
- primary-surface or derived,
- and human-facing or system-facing.

Replica does not mean "different artifact."
It means "same artifact or derivative represented on another local instance."

## 4. Instance provenance

Instance provenance is the part of provenance that records which instance observed, emitted,
changed, mirrored, or synchronized something.

Problem solved:
- in a multi-instance system, "what happened" is incomplete without "where did this action/view
  come from?"

Examples:
- which instance emitted an event,
- which instance last touched a mirror entry,
- which instance produced a receipt,
- which instance currently holds only a partial replica.

Instance provenance should support:
- accountability,
- sync reasoning,
- conflict interpretation,
- and later reconstruction.

It should not redefine the artifact into instance-specific objects unless a narrower implementation
layer explicitly chooses to do so.

## 5. Artifact identity vs instance-local state

Artifact identity is stable across instances.
Instance-local state is not.

Problem solved:
- the same note or retained artifact should remain the same artifact even when:
  - different instances have seen it at different times,
  - one device has stale derived layers,
  - or one device has only a partial replica.

This means:
- `uuid`-like artifact identity should remain above instance-local state,
- instance-local lag or partial visibility should not imply new artifact identity,
- and conflict or sync metadata should usually be read as provenance/accountability semantics rather
  than new ontological artifact classes.

## 6. Eventual consistency

Eventual consistency is the expected convergence posture across instances and replicas in this
system.

Problem solved:
- the system should remain usable without requiring strong immediate consistency across all devices.

This means:
- different instances may temporarily disagree,
- some replicas may lag,
- some derived layers may be incomplete,
- and later sync/rebuild may restore convergence.

Eventual consistency does not mean:
- arbitrary loss of provenance,
- silent overwriting of meaning,
- or treating inconsistent replicas as if no tension exists.

It means delayed convergence is normal and must be accounted for.

## 7. Stable distinctions

### Instance vs artifact

- an instance is a local runtime context,
- an artifact is the thing of meaning.

### Device role vs operational scope

- device role concerns how a device/instance participates practically,
- operational scope concerns the narrower working boundary for retrieval and action.

### Replica vs projection

- a replica concerns where a thing or derivative is carried,
- a projection concerns how an artifact is represented for a bounded purpose.

One replica may contain several projections.
One projection may exist on several replicas.

### Instance provenance vs source role

- instance provenance says where an observation, change, or record came from,
- source role says what epistemic role an artifact plays in a context.

These must not be collapsed into one meaning of `source`.

## 8. Minimal consequences

1. Multi-device use should be described as normal operation, not as a special exception.
2. Artifact meaning should remain stable even when instance state differs.
3. Sync and conflict records should carry instance provenance without pretending they define new
   artifact identities by themselves.
4. Partial replicas and narrower device roles should be treated as legitimate system states.

## 9. Non-goals

This document does not yet define:
- a final sync protocol,
- a final conflict-resolution scheme,
- exact instance metadata fields,
- or whether replica state should be stored in one table, graph, or event family.

Those remain downstream.

## Related documents

- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/HUMAN-FLOWS.md`
- `docs/PROJECT_KERNEL.md`
- `docs/ARCHITECTURE.md`
- `docs/plans/PROTOCOL_SATELLITE_SYNC.md`
- `docs/plans/V60_ARCHITECTURE_TARGET.md`
