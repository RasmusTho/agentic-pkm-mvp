State: Governance doc — term mapping for Companion UI design handoff normalization. Does not claim shipped runtime behavior.
Doc role: Companion UI core term mapping
Authority: Normalization reference for translating Claude Design language into Yggdrasil / Companion UI architecture language
Owner: Companion UI / interaction model
Temporal class: stable
Review cadence: event-driven
Source of truth: authoritative for term normalization
Last reviewed: 2026-05-15
Last verified against: companion-ui/docs/CANVAS_SUGGESTION_FLOW.md, companion-ui/docs/UI_RUNTIME_BOUNDARIES.md, companion-ui/design_handoff/2026-05-14-claude-design-package/, docs/COMPANION_UI_PRODUCT_SPEC.md, docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md, companion-ui/design_handoff/2026-05-14-handoff-governance-pack/, issue #901

# Core Term Mapping

This document maps design-language terms (as they appear in Claude Design explorations, prototypes, and handoff packages) to the architecture and implementation language used in Yggdrasil owner-docs and Companion UI contracts.

Use this mapping when:

- Converting a design handoff into a normalized spec (`companion-ui/docs/`).
- Writing a GitHub issue that references a design package.
- Reviewing whether a PR correctly maps design intent to architecture terms.
- Authoring new handoff packages to ensure they use consistent vocabulary.

## Core term mapping

### System and surface terms

| Design language | Yggdrasil / implementation language | Authority source | Notes |
|---|---|---|---|
| **Companion UI** | Companion UI (same) | `docs/COMPANION_UI_PRODUCT_SPEC.md` | The human-facing product shell. Not a fourth interaction authority surface; it hosts Panel, Chat, and Automation. |
| **Yggdrasil** | Yggdrasil (same) | `docs/ARCHITECTURE.md`, `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` | The local-first cognitive prosthesis and agentic PKM runtime. The full system, not just the UI. |
| **Panel** | Panel | `docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md` | Command-oriented authority surface. Governance receipts surface here. |
| **Chat** | Chat | Same as Panel source | Canvas-like conversation surface. Subordinate to document context. Not a source of truth. |
| **Automation** | Automation | Same as Panel source | Background-execution lane. Separate from Panel and Chat. |
| **vault** | vault / Obsidian vault | `docs/ARCHITECTURE.md` | The Obsidian Markdown vault that is the primary persistence layer. |
| **note** / **document** | vault note / Markdown note | `docs/ARCHITECTURE.md` | A Markdown file in the vault. The document is the primary cognitive anchor. |
| **companion note** | companion note | `docs/ARCHITECTURE.md` | A system-managed note that co-resides with its primary note. Not produced by a user. |
| **Hugin** | Hugin (same) | `docs/COMPONENTS.md`, `docs/ARCHITECTURE.md` | The Panel agent. Command-oriented. Authority surface for governance-bearing mutations. |
| **Munin** | Munin (same) | `docs/COMPONENTS.md` | Background/automation agent. Not a UI-facing agent by default. |
| **margin rail** | margin rail / overlay rail | `companion-ui/docs/OVERLAY_GRAMMAR.md` | The right-margin conversation strip in document-first layouts. Hugin is "a margin voice" in this model. |
| **bottom sheet** | bottom sheet | `companion-ui/docs/OVERLAY_GRAMMAR.md` | Portrait-mode slide-up overlay for suggestions. 3 snap points. |
| **split pane** | split pane | `companion-ui/docs/` | Left conversation + right document layout. One of several layout modes. |

### Mode and state terms

| Design language | Yggdrasil / implementation language | Authority source | Notes |
|---|---|---|---|
| **Find mode** | Find | `docs/COMPANION_UI_PRODUCT_SPEC.md §Mode Model` | Product affordance for retrieval and source citation. |
| **Reorient mode** | Reorient | Same | Product affordance for interruption recovery and situational context. |
| **Resurface mode** | Resurface | Same | Product affordance for memory and prior-work discovery. |
| **Act mode** | Act | Same | Product affordance for governed mutations and write actions. |
| **cognitive mode** | cognitive mode | `companion-ui/docs/COGNITIVE_MODES.md` | The user's current cognitive posture (e.g., deep work, orientation, resurfacing). Declared by the runtime; rendered by UI. |
| **orientation** | orientation / re-entry | `companion-ui/docs/COGNITIVE_MODES.md`, `companion-ui/docs/POSTURE_TRANSITIONS.md` | The moment of re-entering a context after interruption. |
| **staged state** | staged / suggestion-staged | `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` | A proposal is visible and awaiting user action (apply or discard). |
| **apply-pending** | `apply_pending` | `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` | Body edit is being written via `canvas_writer`. Composer disabled. |
| **governance-pending** | `governance_pending` | `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` | Governance action being routed via `GovernanceRouter`. |
| **receipt** | receipt / governance receipt | `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md`, Panel contracts | A structured confirmation returned by the governance pipeline. Surfaces as `ReceiptPill` in UI. |
| **dead-letter** | dead-letter / outbox dead-letter | `docs/ARCHITECTURE.md` | An outbox message that failed all retry attempts. |
| **proof** / **runtime proof** | runtime proof / validation receipt | `docs/STATUS.md`, `docs/ARCHITECTURE.md` | Evidence that the system's current state matches declared invariants. Not a UI concept. |

### Action and pipeline terms

| Design language | Yggdrasil / implementation language | Authority source | Notes |
|---|---|---|---|
| **body edit** / **body-edit lane** | body-edit lane | `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` | User-present co-authoring of the active note body. Applies via `canvas_writer`. No governance receipt. |
| **governance-bearing lane** | governance-bearing lane | `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` | Frontmatter, maturity, cross-note, lifecycle mutations. Queued via `GovernanceRouter`. Returns a receipt. |
| **apply** | apply / `canvas_writer.apply_edit` | `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` | Writes a body edit to the active note. Does not generate a Panel receipt. |
| **queue** | queue / `GovernanceRouter.request_governance_action` | `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` | Routes a governance-bearing intent through the governed pipeline. Returns `receipt_id`. |
| **GovernanceRouter** | `GovernanceRouter` (same) | `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` | The runtime component that gates governance-bearing mutations. |
| **canvas_writer** | `canvas_writer` (same) | `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` | The runtime component that applies body edits to the active note. |
| **outbox** | outbox (same) | `docs/ARCHITECTURE.md` | The durable message queue for governance-bearing events. Not a UI concept. |
| **vault action** / **tool action** | vault action / bounded action | `companion-ui/design_handoff/2026-05-14-vault-action-layer/` (design only) | A registered, policy-gated mutation of the vault via the 9-step pipeline. No owner-doc yet; see open issue #910. |
| **tool tier** | tool tier (1–5) | Design only (Vault Action Layer package) | 5-tier authority taxonomy: read-only / proposal / bounded-write / governance-bearing / forbidden. Not yet in owner-docs. |
| **action pipeline** | 9-step action pipeline | Design only (Vault Action Layer package) | `intent → classify → bound → policy → guard → idempotency → execute → receipt → event`. Not yet in owner-docs. |
| **Obsidian / MCP** | Obsidian adapter / MCP adapter | Design intent (not yet an owner-doc) | Adapter layer, not primary mutation authority. Mutations must still pass through the governed pipeline. |

### Design-system and visual terms

| Design language | Yggdrasil / implementation language | Notes |
|---|---|---|
| **Norse gold** / `--accent` | governance / provenance accent color | Used for governance, Panel receipts, and provenance cues. |
| **electric cyan** / `--cyan` | trigger / link / receipt-pending cue | Used for pending actions and navigation links. |
| **vault green** / `--vault` | healthy / applied / reviewed state | Used for successful completion and vault-healthy states. |
| **amber** / `--amber` | staged / stale / inferred / attention-needed | Used for proposals awaiting user action or content needing verification. |
| **destructive red** / `--destructive` | refusal / denial / conflict / dead-letter | Used for hard failures and write-guard denials. |
| **EB Garamond** / `--font-display` | display serif (section headers) | Marks section boundaries; not used for UI copy. |
| **Space Grotesk** / `--font-ui` | UI sans-serif (body / labels) | Primary readable voice of the UI. |
| **JetBrains Mono** / `--font-mono` | mono (evidence captions, ids, scores, timestamps) | The "this is evidence, not summary" voice. Used for values the runtime emits. |
| **ReceiptPill** | `ReceiptPill` | UI component that surfaces a governance receipt. States: `queued`, `applied`, `pending`, `failed`. |
| **callout** (cyan / amber / accent / destructive / vault) | callout variant | Design-system component for invariant and notes blocks. |

### Authority-layer terms

| Design language | Architecture language | Authority source |
|---|---|---|
| **design exploration** | design exploration | `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md §Handoff chain` |
| **handoff package** | handoff package | Same |
| **normalized spec** | normalized spec | Same; lives in `companion-ui/docs/` |
| **crossing B** | Crossing B (handoff → normalized spec) | Same; requires maturity checklist sign-off |
| **crossing C** | Crossing C (normalized spec → issue) | Same |
| **architecture authority** | owner-docs in `docs/**` | `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` |
| **runtime truth** | shipped code + tests + `docs/STATUS.md` | `docs/STATUS.md`, `docs/ARCHITECTURE.md` |
| **design guidance** | design guidance (not authority) | `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md §Authority boundary` |

## Usage rules

1. **Use architecture language in normalized specs, issues, and PRs.** Design language is acceptable inside a handoff package (README, prototype commentary) because it mirrors the exploration context. Outside the handoff folder, use architecture language.

2. **Do not import design-only terms into owner-docs.** Terms marked "Design only" in the mapping above (vault action tier taxonomy, 9-step pipeline, etc.) must not appear in owner-docs until a separate normalized spec and issue land for them.

3. **Server declares; UI renders.** When mapping design terms to implementation, never let a UI term carry authority over a runtime term. The runtime's declared class wins.

4. **When in doubt, link to the authority source.** If a mapping is ambiguous, add a citation to the authority source rather than resolving the ambiguity unilaterally.

## Open terms (not yet mapped to owner-docs)

These design terms from the 2026-05-14 package lack a corresponding owner-doc entry and must not be treated as architecture authority until the relevant issues are resolved:

| Design term | Design package | Governing issue | Status |
|---|---|---|---|
| 5-tier tool authority taxonomy | `2026-05-14-vault-action-layer` | #910 | Design only |
| 9-step action pipeline | `2026-05-14-vault-action-layer` | #910 | Design only |
| `move_inbox_note_to_workbench` (first bounded action) | `2026-05-14-vault-action-layer` | #910 | Design only |
| `VAULT_ACTION_LAYER_CONTRACT.md` | `2026-05-14-vault-action-layer` | #910 | Future owner-doc; not yet authored |
| Runtime Proof / Health Dashboard (9-question proof surface) | `2026-05-14-runtime-proof-dashboard` | #865, #866, #850 | Design only |
| Context Bundle Inspector (ranked candidates, compact/expanded) | `2026-05-14-context-bundle-inspector` | #894, #895, #896 | Design only |
| Memory Candidate Review Queue (anti-inbox mitigations, persistent banner) | `2026-05-14-memory-candidate-review` | #900 | Design only |
| Static review console (handoff governance pack) | `2026-05-14-handoff-governance-pack` | #901 (follow-on) | Design only |

## References

- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md` — handoff chain and authority boundaries
- `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` — example of a normalized spec; reference for canvas + suggestion terms
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md` — separation of concerns between UI, cognition, and persistence
- `docs/COMPANION_UI_PRODUCT_SPEC.md` — product model; mode and surface authority
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md` — Panel / Chat / Automation authority
- `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` — architecture spine
- `docs/COMPONENTS.md` — Hugin, Munin, and component definitions
- `companion-ui/design_handoff/2026-05-14-claude-design-package/README.md` — 2026-05-14 design session intake table
