# Companion UI

A user-facing module for the agentic PKM system. A PWA client that runs on iPhone, iPad, and Mac, connected to the existing FastAPI runtime over a personal network (Tailscale).

This module does not replace or modify the core system. Obsidian remains the canonical human writing surface. The companion UI is the assisted-thinking shell for cognitive acts that are awkward in Obsidian: canvas-mode conversation with agents, orientation in active cognition, and synthesis workspaces.

## v0 scope

The first build is the **Converse surface** — externalized thinking with an agent, with optional durable output. See `DESIGN_BRIEF.md` for the full context, constraints, and open design questions.

## Design

`DESIGN_BRIEF.md` — the specification and design constraints for this module. This document does not prescribe UI/UX patterns; it defines what the module must accomplish and the hard constraints it must respect. Designers should use this as the starting point for the interaction design.

## Architecture

The companion UI is a client of the existing runtime. It reads from and writes to the vault through the runtime API. All durable state is persisted as markdown files in the vault (chat sessions, staged suggestions, etc.) with documented frontmatter schemas.

Vault compatibility is non-negotiable: markdown must open cleanly in Obsidian without this module present.

## Status

Design stage. Awaiting interaction design and wireframes.
