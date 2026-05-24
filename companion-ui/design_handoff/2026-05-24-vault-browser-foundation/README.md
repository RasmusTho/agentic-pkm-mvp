# Vault Browser Foundation · Design Handoff

**Date:** 2026-05-24
**Status:** Claude Design handoff · v1 · Crossing A (archived; maturity checklist pending)
**Authority:** **Non-authoritative design guidance.** Repo SoT remains authoritative.
**Owner-docs target:** none yet — this is design input, not normalized spec.
**Linked issues:**
- #1259 — *this issue*: land the handoff
- #1260 — workspace shell alignment (prerequisite for browser UI work)
- #1253 — metadata read model
- #1254 — metadata filters and badges
- #1255 — artifact inspector
- #1256 — VaultAction model
- #1257 — agent receipts / review posture
- #1261 — sequencing / planning issue across the foundation stack
**Crossing target:** B (governed handoff chain — see
[`companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`](../../docs/DESIGN_HANDOFF_GOVERNANCE.md)).

## What this is

This package archives the Claude Design handoff for the **Vault Browser
Foundation** workstream. It was produced from a temporary handoff package
containing the Vault Browser capability contract, Companion UI docs,
implementation extracts (companion route + vault-browser tests), and shipped
UAT screenshots.

The package contains:

- A faithful Markdown conversion of the source HTML
  ([`VAULT_BROWSER_DESIGN_HANDOFF.md`](VAULT_BROWSER_DESIGN_HANDOFF.md)).
- A source manifest ([`SOURCE_MANIFEST.md`](SOURCE_MANIFEST.md)) recording the
  inputs that constrain the design and the original-package contents.
- A section-to-issue mapping
  ([`SECTION_TO_ISSUE_MAPPING.md`](SECTION_TO_ISSUE_MAPPING.md)) that ties each
  actionable design recommendation back to the existing implementation issues,
  flags the workspace-shell prerequisite, and lists future-backlog candidates.

## Authority statement

This handoff is **non-authoritative design guidance**. The following SoT docs
remain authoritative and override any design wording they conflict with:

- [`docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md`](../../../docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md)
- [`docs/ARCHITECTURE.md`](../../../docs/ARCHITECTURE.md)
- [`docs/COMPONENTS.md`](../../../docs/COMPONENTS.md)
- [`docs/HUMAN-FLOWS.md`](../../../docs/HUMAN-FLOWS.md)
- [`docs/FRONTMATTER.md`](../../../docs/FRONTMATTER.md)
- [`docs/EVENTS.md`](../../../docs/EVENTS.md)
- [`docs/AGENT_MEMORY/README.md`](../../../docs/AGENT_MEMORY/README.md)
- [`docs/CONTEXTUALIZATION_LAYER/README.md`](../../../docs/CONTEXTUALIZATION_LAYER/README.md)
- [`companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md`](../../docs/PANEL_COMPANION_UI_CONTRACT.md)
- [`companion-ui/docs/MLP_INTERACTION_DESIGN_HANDOFF.md`](../../docs/MLP_INTERACTION_DESIGN_HANDOFF.md)
  (if present)

If a design recommendation conflicts with any of the above, the SoT wins and
the design passage should be treated as a proposal, not a correction. Such
conflicts must be raised through `issue-maintenance-change-control` rather than
absorbed silently.

This handoff is constrained, in particular, by
`docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md` (capability floor and forbidden
behaviors).

## What this handoff informs

- **#1260** — workspace shell orientation alignment (Vault Browser opens into
  this shell; §02 critique is its design input).
- **#1253** — normalized metadata read model.
- **#1254** — metadata filters and badges.
- **#1255** — artifact inspector.
- **#1256** — VaultAction display model.
- **#1257** — agent receipts and review posture.
- **#1261** — foundation-stack sequencing/planning issue.

See [`SECTION_TO_ISSUE_MAPPING.md`](SECTION_TO_ISSUE_MAPPING.md) for the full
mapping and future-backlog candidates.

## How to use this handoff

- Treat the design content as **input** to bounded implementation issues.
- Do **not** use it to implement features outside the scope of an existing
  issue.
- Design recommendations should be converted into bounded issues (via the
  `docs-to-issue` / `feature-breakdown` skills) before implementation.
- The §02 critique of the current workspace shell is the most actionable item
  for the immediate next step (#1260) — see the mapping file.

## Conversion fidelity

The original Claude Design output is an interactive HTML document with
embedded SVG mockups and CSS-driven visualizations. The Markdown conversion
preserves:

- All section headings and numbering (§01–§20).
- All tables (principles, filter dimensions, action modes, slices, etc.).
- All textual rules and "what is forbidden" lists.
- Prose summaries of the SVG mockups (frame contents, row variants, inspector
  tab samples, layout breakpoints) — these are described in text rather than
  reproduced as images.

The conversion is faithful but not byte-exact. Designers needing pixel-level
detail should consult the original source package referenced in
[`SOURCE_MANIFEST.md`](SOURCE_MANIFEST.md).

## Crossing posture

This package lands at **Crossing A** under
[`companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`](../../docs/DESIGN_HANDOFF_GOVERNANCE.md):
archived as design input, not yet promoted to a normalized spec. Promotion to
Crossing B requires the maturity checklist (authority boundaries,
implementation contracts, open questions) to be authored and reviewed. That is
deliberately out of scope for #1259 — landing the handoff in a controlled,
diffable form is the entire goal of this issue.

Subsequent normalized-spec authoring, if any, should happen in
`companion-ui/docs/` and route through the standard handoff-governance chain.
