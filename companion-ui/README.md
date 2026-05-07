# Companion UI Workspace

`companion-ui/` is the workspace for evolving the Agentic PKM companion experience from isolated UI experiments into a structured cognitive interaction architecture.

## Workspace role
- Design workspace: preserves and organizes handoff artifacts and interaction design inputs.
- Cognitive architecture workspace: defines principles, modes, runtime boundaries, and overlay grammar.
- Implementation staging area: hosts prototype app-layer artifacts before production promotion.

## Architectural posture
- Obsidian/vault remains canonical for durable semantic truth.
- Companion UI augments cognition rather than replacing the vault.
- Human remains cognitively centered; AI is assistive and accountable.
- Overlay-first interactions are preferred to hard navigation.
- Chat is subordinate to the active document.
- Runtime state is ephemeral unless explicitly persisted.
- Avoid dashboard-style AI UX and hidden semantic state.
- Preserve compatibility with event-driven runtime, AgentState, staged proposal workflows, provenance overlays, and cognitive continuity.

## Structure
- `docs/` — foundational architecture and cognitive interaction contracts.
- `design_handoff/` — preserved Claude/other design handoff packages.
- `exploration/` — bounded experiments by cognitive mode (`orientation`, `resurfacing`, `synthesis`, `review`, `exploration`).
- `companion-app/` — UI implementation staging files and prototypes.
- `prompts/` — prompt scaffolds (`claude-design/`, `codex/`).

## Current scope
This workspace phase is architecture and interaction focused.

Out of scope in this lane:
- production backend integration work,
- hidden app-specific persistence layers,
- replacing the current overlay-first interaction model.

## Preserved artifacts
- Design brief moved to `docs/DESIGN_BRIEF.md`.
- Existing converse handoff preserved under `design_handoff/2026-05-03-converse/`.
- Existing converse layout prototype preserved under `companion-app/`.
