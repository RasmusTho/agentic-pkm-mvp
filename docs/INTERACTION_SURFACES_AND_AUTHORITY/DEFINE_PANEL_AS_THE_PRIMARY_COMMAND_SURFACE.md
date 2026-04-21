---
name: Define Panel as the Primary Command Surface
description: Clarify that Panel is the primary command-oriented intent surface without making it the only valid user-intent surface
task_id: INTERACTION-08
source_anchor: docs/ARCHITECTURE.md :: Interaction Surfaces
parent_capability: Interaction surfaces and authority boundaries
prerequisites: [INTERACTION-02, INTERACTION-06, INTERACTION-07]
depends_on:
  - DEFINE_PANEL_AUTHORITY_BOUNDARY.md
  - RECONCILE_CHAT_MUTATION_AUTHORITY.md
  - DEFINE_CANVAS_COEDITING_MODEL.md
can_parallelize_with: []
---

State: Compatibility specification. Docs-only. Clarifies v6 interaction-surface semantics without changing runtime behavior, execution pipeline logic, policy mechanics, or persistence schema.
Doc role: Spec
Authority: Compatibility note for interpreting Panel as the primary command-oriented surface alongside Chat as a valid canvas/co-authoring intent surface.
Owner: v6.0 architecture owner
Last reviewed: 2026-04-21
Last verified against: docs/ARCHITECTURE.md, DEFINE_PANEL_AUTHORITY_BOUNDARY.md, RECONCILE_CHAT_MUTATION_AUTHORITY.md, DEFINE_CANVAS_COEDITING_MODEL.md

# Define Panel as the Primary Command Surface

Panel is the primary command-oriented surface for explicit, receipt-bearing user intent.

This does not mean Panel is the only authoritative user-intent surface. Panel and Chat are both valid user-intent surfaces; their difference is interaction structure:
- Panel is command-oriented: explicit action, governed execution, local receipt.
- Chat is canvas/co-authoring-oriented: direct manipulation of thought in an active session, with governance-bearing changes still routed through the gated execution path.

The compatibility rule is:

> "Primary command surface" describes Panel's structure and shipped runtime role. It must not be read as "exclusive intent surface."

Runtime behavior is intentionally unchanged. This document only prevents v6 docs from collapsing the Panel/Chat distinction into an authority hierarchy where Panel is trusted and Chat is merely advisory.
