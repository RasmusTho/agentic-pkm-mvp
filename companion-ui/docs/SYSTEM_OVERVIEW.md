# Companion UI System Overview

## Purpose
`companion-ui/` is a cognitive interaction workspace for Agentic PKM/Yggdrasil. It is not a replacement for Obsidian and not an independent semantic system.

## Core posture
- Obsidian vault remains canonical for durable knowledge artifacts.
- Companion UI augments human cognition; it does not replace human reasoning.
- AI remains contextual, provenance-aware, and subordinate to document-centered work.
- Interaction stays document-first and overlay-first.
- The system should behave as a cognitive prosthesis and continuity-preserving cognition environment for continuity of thought, not as a productivity dashboard, task system, or AI workspace.

## Cognitive architecture baseline
- Document is the cognitive anchor.
- Overlays are continuity surfaces, not separate semantic worlds.
- Cognitive postures replace hard mode framing.
- Cognitive trajectories replace session-fragmented thinking as the main temporal frame.
- Resurfacing is contextual and provenance-aware.
- Attention and interruption semantics are explicit.
- Low attentional load is a design constraint, not an optimization after the fact.
- Hidden semantic state is prohibited.

## System boundary
- In scope: interaction architecture, design artifacts, UI prototyping, prompts, and implementation staging.
- Out of scope here: production backend integrations, hidden persistence systems, dashboard-style autonomous AI UX, notification-centric interaction design, and implementation-coupled runtime modeling.

## Runtime relationship
- Companion UI is a client to the existing runtime (FastAPI + event surfaces).
- Runtime state in the UI is ephemeral unless explicitly persisted to vault-compatible artifacts.
- Event-driven compatibility is required so future runtime/event coordination can plug in without rewriting interaction primitives.

## Workspace roles
- `docs/`: architecture and cognitive interaction contracts.
- `design_handoff/`: preserved external design handoffs and wireframes.
- `exploration/`: bounded experiments by cognitive posture.
- `companion-app/`: implementation staging area for UI prototypes.
- `prompts/`: reusable design/coding prompt scaffolds.

## Related docs
- `COGNITIVE_PRINCIPLES.md`
- `INTERACTION_PRINCIPLES.md`
- `TEMPORAL_COGNITION.md`
- `COGNITIVE_TRAJECTORIES.md`
- `ATTENTION_MODEL.md`
- `COGNITIVE_OBJECTS.md`
