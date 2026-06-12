---
name: Companion UI Visual Alignment Guide
description: Token and component guidance for bringing the live Python/Jinja2 + Tailwind Companion UI closer to the cognitive-load handoff
doc_role: Visual implementation guide
authority: Non-normative visual guidance. Behavior/authority of each surface stays with its owner contract; this guide governs only presentation tokens and component styling. The note body remains primary; nothing here changes governance.
owner: Companion UI / product architecture
last_reviewed: 2026-06-07
source_contracts:
  - docs/COMPANION_UI_COGNITIVE_LOAD_OPERATING_MODEL.md
  - companion-ui/docs/COMPANION_UI_STATE_MAP.md
  - companion-ui/docs/BLOCKED_AND_STALE_STATE_SPEC.md
governing_issue: "new — M2 under #1638"
implementation_state: visual_guide_target
---
State: Visual alignment guide for the live Companion UI. Token-level and component-level; no framework migration. As of 2026-06-07.

# Companion UI Visual Alignment Guide

## Goal and constraints

Bring the live Companion UI closer to the handoff: a calm, dark, expert-grade surface where the note body is unmistakably primary, agent material is clearly non-human, and authority class is legible from colour and position. Prefer CSS-token-level changes. Do not migrate UI frameworks and do not change governance.

## Design tokens

Add or map tokens equivalent to this palette in the base stylesheet:

```css
:root {
  --bg-base:#070b12;
  --bg-surface:#0c1220;
  --bg-raised:#111a2e;
  --bg-overlay:#162038;
  --fg-1:#dce8f0;
  --fg-2:#7a9ab8;
  --fg-3:#3d5570;
  --border:#152030;
  --border-strong:#1e3050;
  --accent:#d4a843;
  --cyan:#00d4e8;
  --vault:#39e87d;
  --agent:#4a9eff;
  --amber:#f09030;
  --destructive:#ff3d3d;
  --au-canonical:var(--vault);
  --au-projection:var(--cyan);
  --au-proposal:var(--agent);
  --au-confirm:var(--accent);
  --au-receipt:#b98be0;
  --au-local:#6b7a90;
  --au-blocked:var(--destructive);
  --font-display:'EB Garamond',Georgia,serif;
  --font-ui:'Space Grotesk',system-ui,sans-serif;
  --font-mono:'JetBrains Mono','Fira Code',monospace;
  --radius-sm:2px;
  --radius-md:4px;
  --radius-lg:6px;
}
```

## Typography

- Display serif: session/note titles, re-entry headings, large moments.
- UI sans: chrome, labels, body UI.
- Mono: vault paths, hashes, ids, timestamps, status pills, receipt fields.
- Sentence case everywhere except proper nouns/module names. No emoji in production UI.
- Note body: approximately 16-19px, line-height around 1.55, max line around 60-66ch, ragged-right, off-white-on-near-black.

## Layout rules

1. **Note body is primary.** Center column, largest reading measure, calmest surface. Panel/agent rail and receipts are visually secondary.
2. **Authority by colour and position.** Each surface carries its class colour on a border or badge. Proposals are agent blue and never appear inside the body. Receipts are receipt-coloured. Local-render controls carry a local-only badge.

## Component recipes

| Surface | Recipe |
|---|---|
| Status bar | Surface background, mono 11px, gold wordmark, vault connected dot, amber degraded pill |
| Note body | Base background, display title, sans body reading measure, active heading in accent |
| Proposal card | Agent border/header, Agent proposal badge, bordered options, consequence block, provenance row |
| Checkbox / option row | Unchecked by default; checked is per-option and never pre-checked |
| Confirmation rail | Confirm, Reject, Defer, and Clarify equally reachable; high-risk requires a forcing function |
| Receipt chip | Receipt border and muted fill, mono outcome/id; idempotent variant distinct from new execution |
| Blocked / stale | Low-intensity border and muted background, never filled alarm/modal |
| Re-entry card | Accent border, "Where you left off," Resume / Open affordance |
| Resurfacing card | Why-now label, one-line reason, source pointer, Open / Snooze / Dismiss when persistence exists |
| Local-only badge | `local-only · not saved to vault` wherever a non-canonical render is active |

## Do not

- Do not put agent proposals inside the note body or receipts inside the proposal rail.
- Do not use filled red alarms or modals for blocked/stale states.
- Do not introduce gradients, emoji, title-case chrome, or extra accents beyond the palette.
- Do not change any endpoint, governance behavior, or write path while re-skinning.

## Acceptance criteria

- The note body is visibly the primary surface.
- Each surface authority class is identifiable from colour and position.
- Blocked/stale states are calm.
- No governance behavior or write path changes; only tokens, partials, and CSS change.
