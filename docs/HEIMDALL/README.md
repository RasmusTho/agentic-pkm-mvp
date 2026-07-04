State: Draft (advisory groundwork, 2026-07-04). Index for the Heimdall "A" artifacts — the docs-only groundwork that unlocks a Fable-5 architecture window for the Heimdall (Event Capture & Attribution) capability. Advisory until enacted through CES/ADR; no runtime behavior, no GitHub work created.
Doc role: Directory index (Draft)
Authority: Index/entry point for the Heimdall groundwork docs. Subordinate to the docs it points at. Claims no shipped reality.
Owner: Architecture / CES stewardship (Rasmus)
Temporal class: strategic
Review cadence: event-driven
Source of truth: the docs indexed below + owner decision session 2026-07-04.

# Heimdall — Event Capture & Attribution (groundwork)

**Heimdall** is a proposed new constituent of the personal agentic ecosystem: continuous observation
of reality, converted into **attributed, timestamped events** with **confidence** and **provenance**.
Its responsibility ends at a **published event**; downstream constituents (Munin = knowledge/memory,
Hugin = agent-runtime) are read-models of that stream.

This directory holds the **"A" artifacts** — docs-only groundwork that fixes the container and hands
a Fable-5 architecture window a bounded problem. **Everything here is advisory** until enacted through
CES/ADR. Nothing here is shipped, and no GitHub work is created by it.

## The artifacts

| # | Artifact | What it fixes |
|---|---|---|
| **A1** | [ECOSYSTEM_SOS_MODEL.md](ECOSYSTEM_SOS_MODEL.md) | Acknowledged-SoS model, three-layer split, monorepo + split-triggers, substrate inventory — *where Heimdall sits* |
| **A2** | [ADR-0043](../adr/ADR-0043-heimdall-naming-and-norse-name-register.md) | Heimdall naming, Norse name register, observability-alias collision fix — *what things are called* |
| **A3** | [CAPABILITY_CHARTER.md](CAPABILITY_CHARTER.md) | FIXED constraints vs. OPEN problems + proposed fitness invariants — *the Fable brief* |
| **A4** | [OWNER_DECISIONS.md](OWNER_DECISIONS.md) | What Fable may not decide + the captured owner decisions — *the guardrails* |
| **A5** | [FABLE_WINDOW.md](FABLE_WINDOW.md) | Companion-doc pattern, model routing, scope boundaries — *how the window runs* |

Read order: **A1 → A2 → A4 → A3 → A5** (container → names → guardrails → brief → mechanics).

## Fixed direction (do not relitigate)

- The ecosystem is an **acknowledged System-of-Systems**; **Yggdrasil = the whole**; Heimdall is a
  **sibling constituent**, not a subsystem of Munin. (A1 §1)
- Heimdall owns the **append-only fact stream**; everything downstream is a projection. (A1 §2)
- Naming: **Yggdrasil** (whole), **Munin** (knowledge/memory), **Hugin** (agent-runtime),
  **Heimdall** (sensor); observability alias → **OEF**. (A2)
- This is a `reshape` relative to the current single-system framing (ADR-0041) and routes through
  CES/ADR at enactment. Not bundled with ADR-0041/0042 (#2855/#2856).

## Status

Docs-only groundwork, delivered via the docs-authoring lane. Owner decisions captured 2026-07-04.
Enactment (glossary reconciliation, contracts, the Fable window itself) is deferred to later,
owner-initiated work; nothing here changes shipped reality.
