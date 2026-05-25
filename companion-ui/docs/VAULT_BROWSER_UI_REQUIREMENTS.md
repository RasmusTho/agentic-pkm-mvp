State: Companion UI requirements document for Vault Browser / Workspace UI. Derived from user UAT feedback and the Claude Design Vault Browser Foundation handoff. Constrained by repo SoT; does not claim runtime/API/UI implementation.
Doc role: Companion UI requirements
Authority: Binding requirements input for downstream Vault Browser / Workspace UI implementation issues, subordinate to repo SoT docs.
Owner: Companion UI product / Vault Browser workstream
Last reviewed: 2026-05-25
Source issue: #1286

# Vault Browser UI Requirements

## Status and authority

This is a Companion UI requirements document for Vault Browser and Workspace behavior.
It turns user UAT feedback and the Claude Design Vault Browser Foundation handoff into explicit,
repo-visible UI requirements for downstream implementation issues.

This document is constrained by:

- `docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md`
- `docs/ARCHITECTURE.md`
- `docs/COMPONENTS.md`
- `docs/HUMAN-FLOWS.md`
- `docs/FRONTMATTER.md`
- `docs/EVENTS.md`
- `docs/AGENT_MEMORY/README.md`
- `docs/CONTEXTUALIZATION_LAYER/README.md`
- `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md`
- `companion-ui/docs/MLP_INTERACTION_DESIGN_HANDOFF.md`
- `companion-ui/docs/COMPANION_UI_TARGET_ARCHITECTURE.md`
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`

The Claude Design handoff remains design guidance. It is not source of truth, runtime truth,
or permission to expand an implementation issue. If this document conflicts with SoT, SoT wins and
the conflict must be handled through `issue-maintenance-change-control` before implementation
continues.

Downstream implementation issues that modify Vault Browser or Workspace UI MUST read this document
before coding. Issue acceptance criteria remain binding; if issue ACs and this document conflict,
stop and run `issue-maintenance-change-control`.

## Source material

- User UAT observations from #1277 / PR #1285.
- `docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md`.
- `companion-ui/design_handoff/2026-05-24-vault-browser-foundation/README.md`.
- `companion-ui/design_handoff/2026-05-24-vault-browser-foundation/VAULT_BROWSER_DESIGN_HANDOFF.md`.
- `companion-ui/design_handoff/2026-05-24-vault-browser-foundation/SECTION_TO_ISSUE_MAPPING.md`.
- `companion-ui/design_handoff/2026-05-24-vault-browser-foundation/IMPLEMENTATION_SEQUENCE.md`.
- `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md`.
- `companion-ui/docs/MLP_INTERACTION_DESIGN_HANDOFF.md`.

## Requirement levels

MUST means a blocking product/UI requirement. A PR that claims to implement affected Vault Browser
or Workspace UI behavior is incomplete if an applicable MUST is unmet.

SHOULD means expected behavior unless SoT contradicts it or the governing issue explicitly defers
it. A PR that does not satisfy an applicable SHOULD must say why.

MAY / FUTURE, also called MAY-FUTURE in issue acceptance criteria, means architecturally enabled
future capability. It is not automatically in scope for the current issue.

NON-GOAL means forbidden behavior or explicitly out-of-scope behavior. Implementations must not
smuggle NON-GOAL behavior into adjacent work.

## R0 Two-note rendering model

The system distinguishes two note types that appear together in a loaded workspace view:

- **Main note**: the human-authored vault note. Its body is clean prose. The user reads and
  edits this content. It is the cognitive anchor of the workspace.
- **Companion note**: a system-managed note stored in the vault companion directory
  (`⚙️ System/companions/<uuid>.md` or equivalent). It holds artifact metadata: uuid, kind,
  trust, review_state, provenance, origin, source_ref, created, updated, and similar fields.

Requirements derived from this model:

- The UI MUST load both the main note and the companion note when a note is opened.
- The UI MUST render only the main note body as the primary reading surface.
- Companion note content MUST NOT appear as part of the main reading area.
- Artifact metadata displayed in the UI (uuid, kind, trust, review posture, provenance) MUST be
  sourced from the companion note where it is available.
- When a companion note is absent, the UI MAY fall back to frontmatter fields in the main note,
  but MUST make it clear that companion metadata is missing.
- Main notes SHOULD be writable as clean human prose without requiring YAML frontmatter.
- The companion note is the authoritative metadata store. Main note frontmatter is a legacy/fallback
  source only.
- This separation MUST NOT be collapsed. A UI that reads metadata only from main note frontmatter
  violates this model and must be corrected.
- Mixing main note body with companion note metadata in the same rendering region is a NON-GOAL.

## R1 Workspace orientation and body rendering

- Raw YAML/frontmatter MUST NOT render as ordinary body text.
- Raw YAML/frontmatter MUST NOT render in any user-visible area outside the bounded
  identity/metadata chrome — including areas adjacent to, above, or below the body frame.
- Human-readable body content MUST be visually distinct from metadata.
- Frontmatter-derived metadata MUST remain visible in bounded identity/metadata chrome where
  available.
- Path, artifact ID/UUID, content hash, and vault/channel identity MUST be findable without
  dominating the reading flow.
- If metadata is unavailable or invalid, the UI MUST show a human-understandable state rather than
  leaking raw implementation detail.
- The note body remains the human cognitive anchor. Metadata chrome supports orientation; it must
  not compete with the body as prose.
- Frontmatter that leaks outside the note body frame but is still user-visible is an R1 violation,
  even if it is not rendered inline with the body text.

## R2 Vault Browser layout

- Default Vault Browser interaction SHOULD be a persistent navigation surface, preferably a
  left-side pane.
- Modal/popup browsing MAY remain only as temporary MLP/fallback behavior or as a narrow action.
- Modal/popup browsing MUST NOT be the target long-term browsing UX.
- The user MUST be able to browse vault files/artifacts while keeping the central note pane visible.
- Clicking a browser entry MUST open the selected note/artifact in the central pane.
- The browser surface MUST support future artifact-aware browsing without becoming graph-first.
- Graph view MAY be added later only as a secondary named browsing mode, never as the primary
  navigation surface.

## R3 Browse -> read -> edit flow

- The core flow MUST support: browse artifact -> open in central pane -> read -> edit when policy
  permits.
- If editing is unavailable, the UI MUST state why in human-facing language.
- Edit availability MUST be governed by WriteGuard/policy.
- Edit unavailability MUST NOT look like a broken UI.
- Unavailable edit actions MUST be rendered as reason/absence states, not active-looking primary
  buttons.
- Body editing, governance writes, and agent proposals MUST remain separate flows.
- Body editing MAY use Canvas or another governed body-editing surface when the governing issue
  permits it; the Vault Browser itself is not an authoring surface.

## R4 Selection reliability and performance

- Selecting a note from the browser MUST be reliable.
- Normal dev-runtime note selection SHOULD complete within 2 seconds for ordinary notes.
- UAT for note selection SHOULD include at least three repeated selections and timings.
- Slow or unreliable selection MUST be treated as a blocker or explicit performance follow-up.
- UAT 2026-05-25 observed ~5s note selection latency on dev runtime. This is a documented blocker;
  root cause investigation is required before this requirement can be marked satisfied.
- Selection MUST NOT rely on client-side access to Mac mini localhost APIs when the UI is opened
  remotely.
- Remote-client UAT matters when the user-visible behavior depends on a browser running on a
  different machine than the runtime host.

## R5 Status/posture and degraded states

- Workspace MUST show one clear primary posture/orientation surface.
- Runtime/vault/WriteGuard/Canvas/update/guard state MUST NOT appear as an unstructured multi-row
  debug dump in the default UI.
- `ok`, `degraded`, `blocked`, and `unavailable` states MUST be visibly distinct.
- Degraded state MUST expose enough information for safe operation without overwhelming the reading
  flow.
- Diagnostic detail MAY remain available in explicit dev/diagnostic surfaces.
- Empty, degraded, blocked, unavailable, and API-error states MUST be distinguishable; the UI must
  not use the same visual treatment for "no notes" and "the runtime cannot answer."

## R6 Actions and disabled controls

- Unavailable actions MUST NOT appear as active-looking primary controls.
- Disabled/unavailable states MUST include a reason when practical.
- Browser actions MUST remain classified according to `docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md`.
- Read-only browsing, UI-only actions, bounded system writes, governance writes, and agent proposals
  MUST remain separate.
- The UI MUST NOT allow hidden writes or LLM-mediated mutation without governance, guardrails, and
  receipts.
- The UI MUST render server/runtime-declared action modes. It MUST NOT invent or reclassify action
  modes locally.

## R7 Human-facing copy

- Internal runtime/test labels MUST NOT leak into default human-facing UI.
- The following examples MUST NOT appear in default UI unless they are under an explicit
  diagnostic/details mode:
  - `user not present`
  - `composer enabled`
  - `thinking`
  - `SUGGESTION idle`
  - `FIND unavailable`
- Internal/test state MAY remain in stable `data-*` attributes.
- Human-facing copy SHOULD explain states in terms of user outcome and safe next action.
- Copy SHOULD preserve authority boundaries: say when a surface is read-only, unavailable, blocked,
  or waiting on policy rather than implying the UI has authority it does not have.

## R8 Right rail and companion surfaces

- Right rail SHOULD be sparse, meaningful, and oriented around current context or clear absence
  states.
- Empty/inactive cards SHOULD collapse or render one clear no-active-session/unavailable state.
- Rail MUST NOT function as an unfiltered debug/status dump in default UI.
- Dev/diagnostic detail MAY exist, but it must be visually separated from the normal orientation
  surface.
- Panel, Canvas, Reorient, Resurface, Find, and Vault Browser surfaces MUST remain semantically
  distinct. Shared visual components are acceptable only where the semantics match.

## R9 Metadata, filters, inspector, actions, receipts

Future bounded issues SHOULD use the Claude Design handoff feature map as implementation input for:

- normalized artifact metadata;
- deterministic metadata filters and badges;
- artifact inspector sections;
- provenance/trust/review posture display;
- VaultAction display modes;
- receipt/review posture states;
- degraded/blocked/error states;
- test IDs / data attributes;
- MLP vs future capability separation.

These expectations inform future bounded issues. They MUST NOT be silently implemented outside
their issue scope. If an issue conflicts with this requirements document, use
`issue-maintenance-change-control` before coding.

The MLP boundary remains explicit:

- MLP v0 supports read-only Markdown enumeration, deterministic text/path/title filtering, active
  vault/channel identity, empty/error/identity-unavailable states, and note selection into the
  Companion workspace.
- Future slices may add metadata, inspector, action, receipt, activity, and relation projections
  only through their own issue contracts.
- Stable `data-*` attributes SHOULD expose internal state for tests without leaking that state as
  visible copy.

## R10 Future capabilities from Claude Design handoff

The following are MAY / FUTURE capabilities. They are not automatically in scope for current
issues and should be extracted into bounded issues through repo workflow:

- saved views;
- timeline/activity browsing;
- artifact relation read model;
- links/relations inspector beyond placeholder;
- graph as secondary browsing mode;
- source/evidence dependency browser;
- review campaigns;
- guarded bulk operations;
- resurfacing candidates;
- duplicate candidates;
- contradiction candidates;
- agent activity explorer;
- responsive/mobile read-only behavior;
- visual hierarchy/density pass.

Graph view is secondary. It is not the primary navigation model, not the default landing, and not a
decorative replacement for artifact rows and the central note pane.

## Non-goals

The Vault Browser / Workspace UI is not:

- a DB-first browser;
- a generic Obsidian clone;
- graph-first;
- hidden automation;
- a place where AI proposals mutate notes directly;
- a place where browsing, body editing, governance writes, and agent proposals collapse into one
  flow;
- a debug dashboard as the default user experience;
- a place where Companion UI reads or writes vault files directly;
- a source of truth over vault Markdown/frontmatter, repo SoT docs, WriteGuard, policy, events, or
  receipts.

## Test and UAT requirements

- UI implementation PRs touching Vault Browser / Workspace MUST state which requirements in this
  document are affected.
- UAT MUST include real browser/client verification when remote-client behavior matters.
- For browse/open flows, UAT SHOULD include:
  - page loads;
  - frontmatter absent from body;
  - browser surface visible;
  - at least three note selections with timings;
  - edit availability or reason visible;
  - unavailable actions not presented as active-looking controls.
- Automated tests SHOULD preserve stable `data-*` attributes for internal states while asserting
  human-facing copy.
- PRs must not claim completion solely from unit tests when visible UAT behavior is the acceptance
  target.
- If normal dev-runtime note selection exceeds 2 seconds for ordinary notes, the PR SHOULD either
  fix it or create an explicit performance follow-up before claiming the browse/open flow is ready.

## Downstream implementation guidance

- #1277 corrective work must satisfy this document where applicable.
- PR #1285 should be re-evaluated against this document before merge/closure if it remains open.
- Future side-pane browser implementation should be its own bounded issue if not already covered.
- Future implementation agents must read this document before modifying Vault Browser / Workspace
  UI.
- If issue ACs and this document conflict, stop and run `issue-maintenance-change-control`.
- Do not use this document to silently expand an issue. Convert MAY / FUTURE requirements into
  bounded issues through the repo workflow before implementation.
- The two-note rendering model (R0) applies to all Vault Browser / Workspace UI implementation
  issues. Implementation must not skip companion note loading, must not mix companion metadata
  into the main note body frame, and must not render main note frontmatter in any user-visible
  region.
- Note selection performance (R4) is a documented blocker as of UAT 2026-05-25. Any PR claiming
  browse/open flow completion must resolve or explicitly defer this with a follow-up issue.
