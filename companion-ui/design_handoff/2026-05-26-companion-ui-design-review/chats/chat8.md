# Companion UI MLP Clarifications

_Started 2026-05-21 17:00 UTC_

---

## User

<system-info comment="Only acknowledge these if relevant">
Project title is now "companion ui"
Project currently has 25 file(s)
Current date is now May 21, 2026
</system-info>

<pasted_text name="Pasted text (433 lines)">
You are helping us design the Minimum Lovable Product for Companion UI, the human-facing shell for a single-user, local-first Agentic PKM system called Yggdrasil / Agentic PKM.

I have attached a folder called `companion-ui-mlp-design-pack`.

Use the attached folder as your primary context.

## How to read the attached folder

Treat these files as product and interaction authority:

- `docs/COMPANION_UI_PRODUCT_SPEC.md`
- `companion-ui/README.md`
- `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md`
- `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md`
- `companion-ui/docs/CANVAS_AGENT_MVP_CONTRACT.md`
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`

Treat these files as current implementation constraints, not final product architecture:

- `companion-ui/current-implementation/serve_dev_page.py`
- `companion-ui/current-implementation/real_note_workspace_dev_page.py`
- `app-api/companion.py`
- `app-api/panel.py`
- `app-api/panel_confirmation.py`

Do not redesign from scratch. Design an MLP that can be implemented incrementally over the current server-rendered Companion UI shell.

## System context

Companion UI is not a new authority surface. It is a product shell that hosts and coordinates existing governed interaction surfaces.

The canonical surfaces are:

1. Canvas
   - Direct, present-user, note-body co-authoring/editing.
   - Body edits may be applied through runtime.
   - Canvas is not the governance/action authority surface.

2. Panel / Act
   - Artifact-local proposal and confirmation surface.
   - Handles governed actions.
   - User reviews proposals and confirms/corrects/rejects them.
   - Confirmed actions route through runtime policy, WriteGuard, idempotency, execution, event emission, receipts, and durable vault-visible projection.

3. Reorient
   - Read-side situational recovery for the active artifact.
   - Helps the user understand “where am I, what changed, what next?”
   - May hand off candidate actions to Panel but must not execute by itself.

4. Resurface
   - Low-pressure return-to-attention suggestions.
   - Must not imply urgency unless runtime explicitly provides an urgency signal.
   - For MLP, it may be read-only if persistence for dismiss/snooze/pin is not implemented.

5. Find
   - Source candidate / citation support.
   - For MLP, it can be narrow and may show unavailable state if backend payload is missing.

The vault / Markdown remains the human-readable canonical surface.
The runtime owns policy, WriteGuard, idempotency, execution, events, receipts, and durable vault-visible projection.
The UI must never write vault files directly.
The UI must never reclassify server-declared proposals locally.
The UI must never make LLM output authoritative.
All mutating actions must route through runtime endpoints.

## Current implementation reality

Current implementation already supports or partially supports:

- Real note loading through `GET /api/companion/workspace`.
- Artifact identity, note path, content hash.
- Runtime/channel labels.
- WriteGuard/canvas-enabled guard state.
- Canvas session open/close.
- Canvas body edit apply through runtime.
- Canvas undo.
- Canvas recovery/conflict state.
- Panel proposal rendering.
- Panel confirm/reject/correct through `POST /api/panel/confirm`.
- Panel receipt/block response rendering.
- Reorient read-side sections from runtime.
- Resurface read-side candidates from runtime.
- Production launch profile exists, but the UI is still minimal.

Important implementation limitation:

The UI is currently a minimal server-rendered staging shell. It is not yet a full frontend app. Design must be implementable incrementally in that context.

Do not assume a full React app unless you clearly mark that as future-state and keep the MLP design implementable in the current shell.

## MLP goal

Design the shortest useful vertical product slice:

Open note → Reorient → Canvas body edit → Panel Act → Receipt

The product should help the user:

1. Open a real active note.
2. Understand where they are.
3. See whether the system is safe to edit.
4. Make a bounded body edit with preview/apply/undo.
5. Review a Panel proposal.
6. Confirm/correct/reject it.
7. See receipt or block reason.
8. Trust that no hidden mutation occurred.

## Core design principle

The UI should be calm, sober, low-friction, and provenance-aware.

Avoid dashboard aesthetics.
Avoid generic chatbot aesthetics.
Avoid autonomous-agent-control-room aesthetics.
Avoid suggestion pressure.
Avoid hiding uncertainty.
Avoid vague “AI magic” language.
Avoid making read-only controls look actionable.

The design should make boundaries visible without overwhelming the user.

## Required output

Produce a structured MLP interaction design handoff with the following sections.

---

# 1. MLP product frame

Include:

- One-sentence product promise.
- What the MLP includes.
- What the MLP explicitly excludes.
- The primary user loop.
- The trust model in plain language.

---

# 2. Workspace layout

Design the main workspace structure:

- Main note area.
- Companion rail.
- Runtime/channel safety indicators.
- Artifact identity display.
- Content hash / version signal.
- Guard state.
- Session state.
- Receipt visibility.
- Responsive behavior:
  - desktop side rail
  - portrait / narrow viewport bottom-sheet approach

Keep this implementable in the current server-rendered shell.

---

# 3. The vertical MLP flow

Design the complete interaction flow:

## 3.1 Open note

Include:

- loading state
- loaded state
- missing note
- unresolved artifact identity
- runtime unavailable

## 3.2 Reorient

Use the practical structure:

- Where am I?
- What changed?
- What next?

Show how to distinguish:

- facts
- inferences
- stale context
- candidates
- open loops

## 3.3 Canvas body edit

Include:

- open session
- body edit composer
- preview
- apply
- discard
- undo
- close session
- session log visibility

## 3.4 Canvas recovery/conflict

Include:

- hash drift
- interrupted/paused session
- recovery-needed banner
- explicit acknowledgement before edits resume

## 3.5 Panel / Act proposal review

Include:

- proposal card
- proposal evidence
- action class
- cognition route
- confirm
- correct
- reject
- expired proposal
- same-turn blocked

## 3.6 Receipt / blocked outcome

Include:

- executed
- logged
- rejected
- blocked by WriteGuard
- blocked by capability/policy
- corrected receipt
- inverse action if available

---

# 4. State model

Define visual treatment and copy guidance for:

- idle
- loading
- running
- active
- read-only
- unavailable
- blocked
- experimental
- receipt-displayed
- error
- recovery-needed
- conflict-detected
- expired proposal
- same-turn blocked
- WriteGuard blocked
- Canvas disabled
- no actionable Panel proposal
- Find unavailable
- Resurface read-only

For each state, include:

- when it appears
- visual treatment
- user-facing copy
- allowed actions
- forbidden actions

---

# 5. Component inventory

Provide MLP-level component specs for:

- ActiveNoteHeader
- RuntimeSafetyStrip
- ArtifactIdentityPill
- ContentHashPill
- CompanionRail
- AffordanceStatusBadge
- ReorientCard
- ReorientSection
- CanvasSessionCard
- BodyEditComposer
- BodyEditPreview
- RecoveryBanner
- PanelProposalCard
- ProposalEvidenceDisclosure
- ConfirmCorrectRejectControls
- ReceiptCard
- BlockReasonCard
- ResurfaceCandidateCard
- FindCandidateCard
- EmptyStateCard
- ErrorStateCard

For each component include:

- purpose
- required data
- optional data
- visible states
- interactions
- implementation notes for current server-rendered shell
- non-goals

---

# 6. Copy and labels

Provide concise user-facing copy for:

- WriteGuard blocked.
- Canvas disabled.
- Session is in-memory/volatile.
- Proposal expired.
- Same-turn execution blocked.
- Governance action queued.
- Body edit applied.
- Undo available.
- No undo available.
- No actionable Panel proposal.
- Find unavailable.
- Resurface read-only.
- Runtime unavailable.
- Artifact identity unresolved.
- Recovery acknowledgement required.
- Hash conflict detected.
- Receipt available.
- Action logged, not executed.
- Action rejected.
- Corrected action executed.

Copy should be plain, precise, and non-dramatic.

---

# 7. Visual hierarchy and style direction

Provide practical guidance for:

- spacing
- typography hierarchy
- density
- rail vs note-body balance
- badges
- receipts
- blocked states
- low-pressure suggestions
- evidence/provenance disclosure
- safe use of accent color

The current design direction is sober, cognitive, document-first, and provenance-aware.
The UI should feel like a working surface, not a dashboard.

---

# 8. Implementation-ready slices

Translate the design into implementation slices.

Use these slices:

1. Honest affordance statuses.
2. Better real-note workspace shell.
3. Canvas body-edit MLP.
4. Panel / Act receipt MLP.
5. Reorient daily recovery view.
6. Resurface read-only cleanup.
7. Find unavailable / candidate state.
8. MLP production launch safety pass.

For each slice include:

- user value
- UI changes
- required runtime data
- acceptance criteria
- test hints
- explicit non-goals
- likely implementation files from the attached folder

---

# 9. Risks and design guardrails

Identify likely risks, especially:

- UI implying authority it does not have.
- UI hiding WriteGuard or degraded state.
- Read-only affordances looking actionable.
- Resurface feeling urgent.
- Panel and Canvas semantics collapsing.
- Receipts feeling ephemeral.
- Session volatility being hidden.
- Too much technical metadata overwhelming the user.
- Server-rendered shell becoming too complex.

For each risk, give a mitigation.

---

# 10. Final MLP definition of done

Provide a clear checklist for when this MLP is “done enough” to use daily.

The checklist should be strict but not overbuilt.

## Hard constraints

- Do not introduce new authority semantics.
- Do not let UI write vault files directly.
- Do not make chat or UI state source of truth.
- Do not collapse Panel and Canvas.
- Do not design a global inbox.
- Do not design autonomous execution.
- Do not hide uncertainty.
- Do not use urgency language for Resurface unless runtime provides an urgency signal.
- Do not assume a greenfield frontend.
- Keep the MLP implementable in the current server-rendered dev/staging shell.
- Mark any future-state ideas clearly as future-state, not MLP.

## Desired output style

Use concrete headings.
Use concise component specs.
Use implementation-ready wording.
Avoid vague design language.
Prioritize what should be built next.
When uncertain, choose the smaller, safer MLP version.
</pasted_text>

<!-- The user attached a local folder named "companion-ui-mlp-design-pack". It may contain a codebase, design components, or other files. Explore it with local_ls("companion-ui-mlp-design-pack") — all paths into this folder must start with "companion-ui-mlp-design-pack/". -->

<!-- The user explicitly selected the following skills for this project, as attachments to their message. These are not optional context — they define how you work. Use them. -->
<attached-skill name="Yggdrasil Design System (design system)">
[Design System] The user selected the **Yggdrasil Design System** design system. This is a binding choice — every visual must follow it, even if the task seems irrelevant. Don't invent colors, type, spacing, or components not grounded here.

    Explore it to find what you need:
    - Always copy out the fonts and colors you need
    - For prototypes and designs, always copy out any relevant components
    - If the design system contains existing mocks of products, and you were asked to design or prototype something similar, copy and fork those mocks to start your design. This helps you make high-quality designs.
    
    Explore it quickly to find relevant UI kits (e.g. mocks of existing products you can copy and fork)

Full system at `/projects/f2b13410-af14-4875-8029-445352123f57/`. Its guide is reproduced below so you don't need to fetch it:

<design-system-guide>
# Yggdrasil Design System

## What This Is

Yggdrasil is a local-first, vault-backed AI second brain for a single power user. It sits atop an Obsidian-compatible markdown vault and adds an agentic assistance layer — capture, triage, retrieval, synthesis, and bounded automation — while keeping all artifacts portable, inspectable, and Obsidian-readable.

The system is named after the Norse world-tree. Its internal modules carry Norse names that reflect their conceptual roles (see Glossary below). The design language inherits that vocabulary: rooted, long-lived, expert-grade, unhurried.

## Sources

- **Codebase (backend runtime):** `RasmusTho/agentic-pkm-mvp` on GitHub — FastAPI, event-driven vault watcher, LangGraph agent runtime, embedding/retrieval stack. No frontend code exists yet.
- **Companion UI brief:** Local mount at `companion-ui/` — `DESIGN_BRIEF.md` and `README.md`. The companion UI is at design stage; no production code exists.
- **No Figma.** No existing visual design. This system establishes the visual language from scratch.

## Products / Surfaces

| Surface | Description | Status |
|---------|-------------|--------|
| **Companion UI** | PWA client for Converse, Orient, Capture — the assisted-thinking shell | Design stage |
| **Obsidian vault** | Primary human writing/reading surface | Operational |
| **CLI** | Operator/developer tooling (`/api/health`, `/api/status`, ingest, retrieval) | Operational |
| **AI Panels + Receipts** | In-note agent suggestion surfaces rendered inside Obsidian | Operational |

The **Companion UI** is the primary design target. v0 ships the **Converse** surface (externalized thinking with an agent, with optional durable output). Future surfaces: Orient, Capture, Triage, Resurface, Synthesize.

Platforms: **iPhone, iPad, Mac.** Desktop is primary; mobile is a thinner subset. This is a PWA over a personal network (Tailscale), not a cloud product.

## Module Glossary (Norse names)

| Name | Role |
|------|------|
| **Mimer** | Knowledge surface — vault, ingestion, indexing, vault-facing agent behavior |
| **Hugin** | Agent and reasoning layer (LangGraph-backed) |
| **Munin** | Planned media and raw-memory module (source artifacts that don't live as vault notes) |
| **Ratatosk** | Ingest and pipeline boundary (routing, normalization) |
| **Brokkr** | Planned execution/deliverable workshop |
| **Tyr** | Planned formal-records boundary (receipts, contracts) |
| **Heimdall** | Infrastructure and observability |

## User Profile

Single user: senior software architect. Daily Obsidian user. Thinks at system level. Not a consumer. Already fluent with markdown, agent tooling, and vault-native workflows. Interaction patterns: capture, synthesis, decision tracking, long-running thought. No onboarding flows, no engagement mechanics.

---

## CONTENT FUNDAMENTALS

### Voice and Tone

- **First person:** "I" from the user's perspective; the system speaks to "you" (the user) when it has a voice at all.
- **Terse.** No filler. Every word earns its place. The user reads dense technical prose all day.
- **Declarative, not conversational.** Agent contributions read like a careful colleague, not a customer service bot. No exclamation points. No "Great question!"
- **Precise.** Words like "artifact," "surface," "vault," "receipt," "contract," "authority" are used in their technical sense and not avoided.
- **No emoji.** Never. Not even in documentation.
- **Sentence case** for all UI labels, headings, and copy. Never title case for UI chrome. Reserved for proper nouns and system module names (Mimer, Hugin, etc.).
- **Imperative for actions:** "Capture," "Synthesize," "Orient" — cognitive verb labels, not noun-phrase labels like "Capture Tool."
- **Provenance is surfaced, not hidden.** When the agent contributes, it is labeled. Suggestions are labeled as suggestions. Sources are cited. Nothing is laundered into uncited truth.
- **No growth loops.** No streaks, no prompts to "keep going," no engagement language.

### Example Copy Patterns

| Context | Example |
|---------|---------|
| Empty state | "No open sessions." (not "Start your first session!") |
| Agent suggestion | "Suggested: restructure this section into three sub-claims." |
| Vault sync | "Vault unreachable." (not "Oops! Can't connect 😅") |
| Action label | "Capture" / "Orient" / "Synthesize" |
| Commit action | "Apply" / "Discard" |
| Error | "Session log could not be written. Runtime unreachable." |
| Provenance | "Source: Inbox/2026-04-22-meeting.md · indexed 2d ago" |

---

## VISUAL FOUNDATIONS

### Color Vibe

Dark-primary. Warm near-black backgrounds (not cold blue-black), parchment-toned text. Norse gold as the primary accent — earned, not decorative. A muted forest green for states that reference the vault/tree. Agent contributions are distinguished by a cool blue-gray, clearly non-human in origin. No bright colors. No gradient washes.

### Color System

Defined in `colors_and_type.css`. See also `preview/` cards.

- **Backgrounds:** `--bg-base` (deepest), `--bg-surface`, `--bg-raised`
- **Foreground:** `--fg-1` (primary, warm off-white), `--fg-2` (secondary/muted), `--fg-3` (dim/disabled)
- **Borders:** `--border`, `--border-strong`
- **Accent gold:** `--accent` — used sparingly for active states, focus rings, key affordances
- **Vault green:** `--vault` — vault-connection, indexed state, growth
- **Agent blue:** `--agent` — all agent-contributed content/UI
- **Amber:** `--amber` — warnings, staged/uncommitted state
- **Destructive:** `--destructive`

### Typography

- **Display serif (EB Garamond):** Used for the Yggdrasil wordmark, session titles, and large heading moments. Conveys depth and longevity. Not used for UI chrome.
- **UI sans (DM Sans):** All interface chrome, labels, body copy inside the app. Clean, slightly geometric, not overused.
- **Monospace (JetBrains Mono):** All code, frontmatter, vault paths, metadata values, timestamps. First-class — this user lives in markdown.

Type scale uses `rem` units with a 16px base. Display sizes reserved for moments of emphasis; UI chrome stays compact (13–15px). Line heights are tighter than consumer apps — this user reads dense content.

### Spacing

8px base unit. Standard gaps: 4, 8, 12, 16, 24, 32, 48, 64. Dense by default.

### Backgrounds / Imagery

- No background images, no textures, no grain (this is a technical tool).
- No gradients except subtle surface-level transitions (e.g. a fade from `--bg-base` to `--bg-surface` within a panel).
- No full-bleed imagery. The vault is the content; the UI gets out of the way.

### Cards and Surfaces

- Cards: thin `1px` borders (`--border`), minimal border-radius (`4px`), no drop shadows by default. Shadow only used for floating elements (modals, popovers) — `0 4px 16px rgba(0,0,0,0.4)`.
- Panels are dark surfaces with subtle borders. Not "cards" in the consumer sense.

### Corner Radii

- `--radius-sm: 3px` — input fields, inline elements
- `--radius-md: 6px` — cards, panels
- `--radius-lg: 10px` — modals, drawers
- `--radius-full: 9999px` — pills/badges only

### Animation and Motion

- Minimal. Purposeful fades only. `150ms ease` for micro-interactions (hover, focus). `250ms ease` for panel transitions. No bounces, no spring physics, no decorative motion.
- Agent "thinking" state: subtle pulse animation on the agent badge, nothing more theatrical.

### Hover and Press States

- Hover: background lightens by one step (`--bg-surface` → `--bg-raised`). No color shift on text.
- Active/press: background darkens slightly + 1px inset shadow.
- Destructive hover: `--destructive` background at 15% opacity.
- Focus: `2px solid var(--accent)` outline, `2px` offset. Never hidden.

### Iconography

- **Lucide** icon set (CDN). Stroke-weight `1.5`, size `16px` for UI chrome, `20px` for prominent actions. Never filled icons.
- No emoji as icons. No unicode stand-ins. No custom hand-drawn icons.
- See `README.md § ICONOGRAPHY` for full usage guide.

### Use of Transparency and Blur

- Blur (`backdrop-filter: blur`) only for floating overlays where the underlying surface provides orientation context (e.g., a command palette over a document). Never decorative.
- Transparency used for layering surfaces, not for visual effect.

### Imagery Color Vibe

- No imagery in v0. If photography is ever added: warm, desaturated, archival tone. No stock photo brightness.

---

## ICONOGRAPHY

**Icon system: Lucide** (`https://unpkg.com/lucide@latest/dist/umd/lucide.min.js` or inline SVGs from the Lucide package)

No built-in icon font exists in the codebase. No custom SVGs were found in the repo. No existing icon assets to copy.

**Substitution flag:** Lucide has been selected as the closest match to the design character — thin stroke (1.5px), geometric, no fill, technically precise. If the team later adopts a different set (Phosphor, Heroicons), update this section and the CDN reference in `colors_and_type.css`.

**Usage rules:**
- All icons: `stroke-width="1.5"`, color inherited from text (`currentColor`)
- UI chrome icons: 16×16px
- Prominent action icons: 20×20px
- Never use icons as the sole affordance — always pair with a text label unless in a well-established toolbar
- No emoji substitutes

**Common icon vocabulary:**

| Concept | Lucide name |
|---------|-------------|
| Capture | `circle-dot` |
| Orient | `compass` |
| Converse | `message-square` |
| Synthesize | `layers` |
| Resurface | `refresh-cw` |
| Triage | `filter` |
| Vault | `archive` |
| Agent | `cpu` |
| Note | `file-text` |
| Session | `scroll` |
| Source | `link` |
| Receipt | `receipt` |
| Settings | `settings` |
| Search | `search` |

---

## File Index

| Path | Contents |
|------|----------|
| `README.md` | This file — system overview, content fundamentals, visual foundations, iconography |
| `colors_and_type.css` | All CSS custom properties: colors, type scale, spacing, radii, shadows |
| `assets/` | Logo wordmark SVG, icon usage examples |
| `preview/` | HTML card files registered in Design System tab |
| `ui_kits/companion-ui/` | High-fidelity UI kit for the Companion UI PWA |
| `SKILL.md` | Agent skill entrypoint |

</design-system-guide>

For assets and UI kits beyond the guide: `read_file("/projects/f2b13410-af14-4875-8029-445352123f57/<path>")` and `copy_files` to bring them into the current project.
</attached-skill>

## Assistant

_[tool: local_ls]_

_[tool: list_files]_

_[tool: list_files]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: local_read]_

_[tool: local_read]_

_[tool: local_read]_

_[tool: local_read]_

_[tool: local_read]_

_[tool: local_read]_

_[tool: local_read]_

_[tool: local_grep]_

_[tool: update_todos]_

I have enough context. Let me build the MLP design handoff. This is a substantial document — I'll create:

1. A long-form handoff HTML with all 10 sections
2. Inline visual mockups of the workspace at every state in the vertical flow
3. Component spec cards
4. State-treatment grids

I'll restrain the Tron flourishes — the brief asks for calm/sober, so I'll use the DS tokens but turn down glows.

_[tool: copy_files]_

Now the workspace shell mockup — parameterized so I can render the same layout in every flow state.

_[tool: write_file]_

Now a small components/state gallery file:

_[tool: write_file]_

Now the main handoff document. I'll keep prose as plain HTML for direct editability and use React only inside the dedicated mockup slots.

_[tool: write_file]_

_[tool: show_html]_

_[tool: show_html]_

_[tool: get_webview_logs]_

Clean. Let me hand off and fork the verifier.

_[tool: done]_

_[tool: fork_verifier_agent]_

Delivered. The handoff is one long-form HTML document — sober, document-first, in the Yggdrasil tone — with the 10 required sections and live workspace mockups for every step of the canonical flow.

**Structure:**
- §1 Product frame · §2 Workspace layout (desktop + narrow bottom-sheet mockups) · §3 Vertical MLP flow (6 framed states: open → reorient → canvas composer / preview / applied → recovery → panel staged / confirming → receipt / blocked) · §4 State model (19-state grid) · §5 Component specs (21 components) · §6 Copy table · §7 Tone + type specimens · §8 Eight implementation slices · §9 Risks/mitigations · §10 DoD checklist

**Files:**
- `Companion UI MLP Handoff.html` — main doc
- `workspace.jsx` — parameterized workspace shell, one component per rail card, all flow states
- `gallery.jsx` — state grid, component specs, copy table, slice cards, risks, DoD
- `colors_and_type.css` — Yggdrasil DS tokens (glow turned down where it would feel dashboard-y)

**Caveats / next steps:**
- All MLP-implementable in the current Python server-rendered shell; no React assumed in production. The JSX is the target shape for visual reference.
- Future-state items (memory promotion UX, plan-staged Panel, dismiss/snooze persistence for Resurface) are marked future-state, not MLP.
- If you want, I can fork this into per-slice handoff fragments, or add ASCII state-transition diagrams for the Canvas + Panel state machines.

## User

Review the Companion UI MLP handoff you produced and create a prioritized “implementation clarification addendum” for the current server-rendered shell.

Focus only on:
1. Which UI details are required for MLP vs future-state.
2. Which states must be visually distinct in the first implementation.
3. Which components can be simplified or combined for MLP.
4. Any copy that could accidentally imply hidden authority, persistence, urgency, or direct execution.
5. A final recommended build order for issues #1178–#1188.

Do not add new product scope.
Do not redesign the layout.
Do not introduce new surfaces.
Do not assume React/Vite.
Keep the output short and implementation-oriented.

## Assistant

_[tool: write_file]_

