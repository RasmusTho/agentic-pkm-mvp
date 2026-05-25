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

## R1 Workspace orientation and body rendering

- Raw YAML/frontmatter MUST NOT render as ordinary body text.
- Human-readable body content MUST be visually distinct from metadata.
- Frontmatter-derived metadata MUST remain visible in bounded identity/metadata chrome where
  available.
- Path, artifact ID/UUID, content hash, and vault/channel identity MUST be findable without
  dominating the reading flow.
- If metadata is unavailable or invalid, the UI MUST show a human-understandable state rather than
  leaking raw implementation detail.
- The note body remains the human cognitive anchor. Metadata chrome supports orientation; it must
  not compete with the body as prose.

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
