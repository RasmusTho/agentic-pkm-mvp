# Companion UI System Overview

## Purpose
`companion-ui/` is a cognitive interaction workspace for Agentic PKM/Yggdrasil. It is not a replacement for Obsidian and not an independent semantic system.

## Core posture
- Obsidian vault remains canonical for durable knowledge artifacts.
- Companion UI is an augmentation layer for orientation, dialogue, synthesis, and review.
- The human remains cognitively centered; AI assists, proposes, and cites.
- Interaction is document-first and overlay-first.

## System boundary
- In scope: interaction architecture, design artifacts, UI prototyping, prompts, and implementation staging.
- Out of scope here: production backend integrations, hidden persistence systems, and dashboard-style autonomous AI UX.

## Runtime relationship
- Companion UI is a client to the existing runtime (FastAPI + event surfaces).
- Runtime state in the UI is ephemeral unless explicitly persisted to vault-compatible artifacts.
- Event-driven compatibility is required so future AgentState/LangGraph flows can plug in without rewriting interaction primitives.

## Workspace roles
- `docs/`: architecture and cognitive interaction contracts.
- `design_handoff/`: preserved external design handoffs and wireframes.
- `exploration/`: bounded experiments by cognitive mode.
- `companion-app/`: implementation staging area for UI prototypes.
- `prompts/`: reusable design/coding prompt scaffolds.
