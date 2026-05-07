# Interaction Principles

## Document-first
- The active document remains the primary cognitive anchor.
- Chat, source peek, and suggestion controls are secondary overlays.

## Overlay-first
- Prefer local overlays (rail, drawer, bottom sheet, source peek) over route changes.
- Preserve context anchoring: where the user was, what was being referenced, and why.

## Posture continuity
- Favor cognitive postures over hard mode switching.
- Allow posture shifts without full-screen context replacement.
- Preserve thread continuity across posture transitions.

## Chat subordination
- Chat supports document-centered thinking.
- Session/thread UI should not become the primary navigation object.

## Provenance visibility
- Keep citations, proposal anchors, and contextual lineage legible at interaction time.
- Avoid provenance hidden only in late audit surfaces.

## Explicit persistence
- Clearly distinguish transient interaction state from persisted artifacts.
- Persist only with explicit user intent and vault-compatible representation.

## Related docs
- `COGNITIVE_MODES.md`
- `OVERLAY_GRAMMAR.md`
- `ATTENTION_MODEL.md`
- `POSTURE_TRANSITIONS.md`
