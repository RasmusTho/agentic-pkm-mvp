# Attention Model

## Purpose
Define explicit attention semantics for document-first cognitive interaction without collapsing attention into visual style, notification logic, or rigid priority scoring.

## Boundary note
- This document defines the semantic model of attention.
- `ATTENTIONAL_PHYSICS.md` defines the newer sub-terms such as attentional weight, gravity, and interruption pressure.
- Metaphorical language is allowed only when it maps back to explicit architectural semantics.

## Attention layers
- **Focal:** currently active trajectory and immediate object set.
- **Peripheral:** nearby context relevant to the current trajectory.
- **Dormant:** unresolved but currently inactive trajectories with remaining resurfacing potential.

## Attention movement
- Orientation expands peripheral visibility.
- Exploration shifts focal attention across alternatives.
- Synthesis narrows attention toward integration.
- Review stabilizes attention on decisions and commitments.
- Recovery restores attention after interruption.

## Core relations
- Salience influences attention, but does not fully determine it.
- Tension can pull attention back even when a trajectory is not currently focal.
- Provenance affects trust and therefore affects whether resurfaced material deserves attention.
- Persistence affects what can survive attention loss, but attention itself is not a persistence layer.

## Preservation rules
- Interruptions must preserve at least one recoverable attention anchor.
- Overlay changes must not silently move objects between durable and transient states.
- Resurfacing should promote dormant objects only when salience and provenance justify it.
- Attention support should minimize interruption cost rather than maximize visible cues.

## Attention loss risks
- Context fragmentation from route-level resets.
- Unlabeled provenance causing trust delays.
- Excess resurfacing that fractures focal attention.

## Attention integrity constraints
- No hidden semantic state.
- No dashboard-first attention capture.
- No chat-centric takeover of document cognition.

## Related docs
- `TEMPORAL_COGNITION.md`
- `COGNITIVE_TRAJECTORIES.md`
- `POSTURE_TRANSITIONS.md`
- `SALIENCE_AND_TENSION.md`
- `ATTENTIONAL_PHYSICS.md`
- `TEMPORAL_PROVENANCE.md`
