State: Governance doc — defines the design-handoff chain for Companion UI. Does not claim shipped runtime behavior.
Doc role: Companion UI handoff governance
Authority: Handoff chain and authority boundaries for design explorations entering the Yggdrasil implementation pipeline
Owner: Companion UI / interaction model
Temporal class: stable
Review cadence: event-driven
Source of truth: authoritative for the handoff chain
Last reviewed: 2026-06-10
Last verified against: companion-ui/design_handoff/, companion-ui/prompts/claude-design/README.md, docs/COMPANION_UI_PRODUCT_SPEC.md, docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md, docs/INTEGRATION_FABRIC_CONTRACT.md, docs/CAPABILITY_CONTRACT_MODEL.md, companion-ui/design_handoff/2026-05-14-claude-design-package/README.md, companion-ui/design_handoff/2026-05-14-handoff-governance-pack/, companion-ui/design_handoff/2026-06-09-system-entry-point/, issue #901

# Design Handoff Governance

This document defines how Claude Design explorations become normalized implementation inputs inside the Yggdrasil / Companion UI repo — without becoming architecture authority or runtime truth on the way.

## Handoff chain

Every Claude Design exploration that is intended to influence Companion UI implementation must travel the following chain before any production code or owner-doc changes are made:

```
exploration → handoff package → normalized spec → GitHub issue → PR → validation receipt
```

| Step | What it is | Who owns it | Lives in |
|---|---|---|---|
| **exploration** | Interactive Claude Design session; HTML prototype + chat transcripts; free exploration of ideas | Designer / operator | `companion-ui/design_handoff/<date>-<name>/` |
| **handoff package** | Archived folder of the exploration output: prototype HTML, design notes, state gallery, implementation contracts, authority boundaries, open questions | Designer / operator | `companion-ui/design_handoff/<date>-<name>/` |
| **normalized spec** | Human-reviewed summary that maps design intent to Yggdrasil architecture language; sits in `companion-ui/docs/` | Repo maintainer | `companion-ui/docs/*.md` |
| **GitHub issue** | Bounded implementation task derived from the normalized spec; references source docs | Agent / maintainer | GitHub Issues (`agent:ready`, scoped scope) |
| **PR** | Implementation of the issue; references the issue and the normalized spec | Agent / maintainer | GitHub PRs |
| **validation receipt** | CI pass + acceptance criteria verified; closed issue; updated status docs | Agent / maintainer | GitHub + `docs/STATUS.md` |

### Crossings

Each step-to-step transition is a **crossing**. The crossings that require explicit review are:

- **Crossing B (handoff → normalized spec):** A human reviewer or designated Codex agent verifies the maturity checklist (see below) and confirms that no design-only concerns leak into the normalized spec as architecture claims or runtime assertions.
- **Crossing C (normalized spec → issue):** The issue author confirms scope is bounded, acceptance criteria are verifiable, and no out-of-scope work is included.
- **Crossing D (PR → merge):** Standard CI + review; confirms no runtime behavior changed outside the issue scope.

Crossings A (exploration → handoff) and E (merge → receipt) are automatic / no formal gate required.

### Maturity checklist (Crossing B)

A handoff package passes Crossing B when all of the following are true:

- [ ] The package README names the surface it covers and declares its authority status ("Visual guidance only" or equivalent).
- [ ] `authority-boundaries.md` is present and distinguishes: design guidance / normalized spec / architecture contract / runtime truth.
- [ ] `implementation-contracts.md` is present and lists the state enum, allowed transitions, and data attributes.
- [ ] `open-questions.md` is present; each open question is triaged into: resolve-before-promotion / resolve-in-normalized-spec / defer-to-implementation-issue.
- [ ] No crossing-B-blocking open questions remain unresolved.
- [ ] The state gallery covers every declared state.
- [ ] The package does not assert current runtime behavior unless explicitly cited from a shipped owner-doc.

If any item is missing, the package remains at Crossing A until the reviewer signs off.

## Authority boundary

Design artifacts are **guidance and input only**. They are not:

- **Architecture authority.** Architecture authority lives in `docs/**` owner docs — specifically `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`, `docs/INTEGRATION_FABRIC_CONTRACT.md`, `docs/CAPABILITY_CONTRACT_MODEL.md`, and the interaction-surface contracts under `docs/INTERACTION_SURFACES_AND_AUTHORITY/`.
- **Runtime truth.** Runtime truth lives in shipped code, tests, `docs/STATUS.md`, `docs/ARCHITECTURE.md`, and validation receipts.
- **A schema declaration.** Design prototypes reference fields and attributes; they do not declare them. Schema changes go through owner-doc PRs.
- **A claim about current behavior.** Unless a design passage explicitly cites a shipped owner-doc, assume it is target-state.

This boundary is absolute. A design artifact that appears to contradict an owner-doc does not win. The owner-doc wins and the design passage should be treated as a proposal, not a correction.

### Invariants this governance honors

The following invariants apply to every handoff package and every normalized spec derived from one:

- **Gated execution.** No interaction surface designed in a handoff package may mutate durable state outside the existing governed path: policy, validation, event pipeline, deterministic writer.
- **Authority separation.** Chat is a canvas surface; Panel is the command surface; Automation is its own lane. Handoff packages do not collapse them.
- **Provenance visibility.** Where a design shows agent-contributed content, it shows source, trust state, and authority flags.
- **Memory candidacy.** Where a design touches agent memory, it never treats candidate memory as semantic authority. "Unreviewed memory is not semantic authority."
- **Server declares; UI renders.** The runtime declares class, posture, and authority. The UI renders what the server declares. The UI never re-classifies.

## Folder shape

Each handoff package lives at:

```
companion-ui/design_handoff/<YYYY-MM-DD>-<slug>/
```

Required files for a Crossing-B-eligible package:

```
README.md                   — what the package is, authority status, crossing target
prototype.html              — self-contained interactive prototype
design-notes.md             — visual rationale (optional for minimal packages)
state-gallery.md            — every UI state described
implementation-contracts.md — state enum, transitions, data attributes, intents
authority-boundaries.md     — what this design is / is not
open-questions.md           — unresolved questions with proposed owners
```

Optional:

```
colors_and_type.css         — shared design tokens (import from sibling packages if unchanged)
spec_chrome.css             — shared spec layout (import from sibling packages if unchanged)
edge-states.md              — degraded / empty / loading / blocked / narrow states
```

The index package `<date>-claude-design-package/` holds the executive summary, intake table, and CHANGELOG for a multi-package session. It is not a package itself — it does not require its own `prototype.html`.

## Handoff archive

Packages already archived in `companion-ui/design_handoff/`:

| Package | Date | Crossing | Related issue(s) |
|---|---|---|---|
| `2026-05-03-converse` | 2026-05-03 | A (pre-governance) | — |
| `2026-05-08-cognitive-temporal` | 2026-05-08 | A (pre-governance) | — |
| `2026-05-11-canvas-suggestion-flow` | 2026-05-11 | B+ (normalized spec exists: `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md`) | #868–#874 |
| `2026-05-14-handoff-governance-pack` | 2026-05-14 | B (this governance doc is the normalized spec output) | **#901** |
| `2026-05-14-runtime-proof-dashboard` | 2026-05-14 | A | #865, #866, #850 |
| `2026-05-14-context-bundle-inspector` | 2026-05-14 | A | #894, #895, #896 |
| `2026-05-14-memory-candidate-review` | 2026-05-14 | A | #900 |
| `2026-05-14-vault-action-layer` | 2026-05-14 | A | #910 |
| `2026-05-14-claude-design-package` | 2026-05-14 | A (index only) | #901 (governance), others per package |
| `2026-05-15-panel-interaction` | 2026-05-15 | A (accepted as design intent — #994) | #977, #978, #981, #994 |
| `2026-06-09-system-entry-point` | 2026-06-09 | B (PROMOTE — normalized spec authoring unblocked; promotion scope excludes the context lane / place band, which remain at Crossing A pending Q15–Q16) | — |

Pre-governance packages (`2026-05-03`, `2026-05-08`) do not require retroactive maturity-checklist completion. They remain valid exploration archives.

## Do not implement yet

The following are explicitly not authorized by this governance doc. They remain downstream:

- **Production Companion UI components** for packages 02–05 (runtime-proof dashboard, context bundle inspector, memory candidate review, vault action layer). Each requires a separate normalized spec and bounded issue before implementation.
- **The review console** described in the handoff governance pack. It is a design prototype; it is not production code. Implementation requires a dedicated issue.
- **New owner-docs** for packages 02–05. These are proposed in the design package README but require human review before authoring.
- **Implementation issues #868–#874** (canvas suggestion flow). These were defined prior to this governance doc and remain their own task contracts. This doc does not absorb or modify them.

## How to introduce a new design exploration

1. Run the Claude Design session using prompts from `companion-ui/prompts/claude-design/`.
2. Export the output into a new dated folder under `companion-ui/design_handoff/`.
3. Ensure the folder shape matches the requirements above (README, authority-boundaries, implementation-contracts, open-questions).
4. Update `companion-ui/design_handoff/README.md` with the new entry.
5. Route to Crossing B when the maturity checklist is complete.
6. After Crossing B approval, author a normalized spec in `companion-ui/docs/`.
7. Create a bounded GitHub issue from the normalized spec.
8. Implement via the standard `issue-to-code` flow.

## References

- `companion-ui/docs/CORE_TERM_MAPPING.md` — maps design-language terms to architecture terms
- `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` — example of a normalized spec derived from a handoff
- `companion-ui/design_handoff/2026-05-14-claude-design-package/README.md` — intake summary for the 2026-05-14 design session
- `companion-ui/design_handoff/2026-05-14-handoff-governance-pack/` — the design prototype that proposed this chain
- `docs/COMPANION_UI_PRODUCT_SPEC.md` — product model; authority on Companion UI surfaces and modes
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md` — interaction surface authority
- `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` — architecture spine
- `docs/INTEGRATION_FABRIC_CONTRACT.md` — integration fabric contracts
- `docs/CAPABILITY_CONTRACT_MODEL.md` — capability contract model

## Crossing B review log

Reviews conducted by Codex agent under issue #956 on 2026-05-17.

| Package | Reviewer | Date | Verdict | Notes |
|---|---|---|---|---|
| `2026-05-14-runtime-proof-dashboard` | Codex / #956 | 2026-05-17 | **PROMOTE** | All 7 checklist items pass. 6 open questions triaged (5 deferred, 1 to normalized spec). Owner-doc `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` shipped; "runtime-proof receipt contract" is proposed/not yet authored — package correctly qualifies it. |
| `2026-05-14-context-bundle-inspector` | Codex / #956 | 2026-05-17 | **PROMOTE** | All 7 checklist items pass. 6 open questions triaged (1 deferred, 5 to normalized spec). Owner-docs `CONTEXT_BUNDLE_CONTRACT.md` and `INTERACTION_SURFACES_AND_AUTHORITY/` shipped. Implementation issue #894 blocked — does not gate design promotion. |
| `2026-05-14-memory-candidate-review` | Codex / #956 | 2026-05-17 | **PROMOTE** | All 7 checklist items pass. 7 open questions triaged (5 deferred, 2 to normalized spec). Owner-doc `AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` shipped. Implementation issue #900 blocked — does not gate design promotion. |
| `2026-05-14-vault-action-layer` | Codex / #956 | 2026-05-17 | **PROMOTE** | All 7 checklist items pass. 7 open questions triaged (1 deferred, 6 to normalized spec). Q1 and Q4 (provisional blockers in package) do not block: both have coherent design positions the normalized spec should confirm. Primary owner-doc `VAULT_ACTION_LAYER_CONTRACT.md` is proposed/not yet authored — expected; authoring it is the normalized-spec output. |
| `2026-06-09-system-entry-point` | Claude Code / handoff intake 2026-06-10 | 2026-06-10 | **PROMOTE** | All 7 checklist items pass. README declares "Visual / interaction guidance only" authority and Crossing target B; authority-boundaries.md present and distinguishes guidance/spec/contract/runtime; implementation-contracts.md lists state enum, transitions, data attributes, and intent vocabulary; open-questions.md triages Q1–Q20 (Q1–Q3 resolved; Q15–Q16 are resolve-before-promotion and remain open, so the context lane / place band are **excluded from this promotion's scope** and stay at Crossing A until Q15–Q16 resolve — no blocker applies to the rest of the package); state gallery covers every declared state incl. edge states; only shipped runtime behavior cited is `GET /api/companion/orientation` per `WORKSPACE_ORIENTATION_CONTRACT.md`. |

### Handoff archive update

The packages above advance from Crossing A to Crossing B as of this review. The handoff archive table should reflect:

| Package | Crossing after this review |
|---|---|
| `2026-05-14-runtime-proof-dashboard` | B (PROMOTE — normalized spec authoring unblocked) |
| `2026-05-14-context-bundle-inspector` | B (PROMOTE — normalized spec authoring unblocked) |
| `2026-05-14-memory-candidate-review` | B (PROMOTE — normalized spec authoring unblocked) |
| `2026-05-14-vault-action-layer` | B (PROMOTE — normalized spec authoring unblocked) |

Downstream normalized-spec authoring issues should be created separately per the "Do not implement yet" section. Each is gated on this review completing, not on upstream implementation blockers.
