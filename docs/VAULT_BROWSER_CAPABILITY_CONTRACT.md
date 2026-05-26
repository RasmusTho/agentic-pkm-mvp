State: SoT v5.5 baseline + v6 active planning direction. Long-term Vault Browser capability contract; not a current-state claim that every concept named below is implemented today. The shipped read-only browser is bounded as `Vault Browser MLP v0` (see §6).
Doc role: Core SoT
Authority: Canonical contract for the Vault Browser as a human-first, vault-driven, governed navigation and orientation surface over the vault. Owns the capability definition, the nine core concepts, the action-class boundary, the MLP-versus-future capability map, and the non-goals/anti-patterns. Does not replace `docs/ARCHITECTURE.md` for current runtime baseline, `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md` for Panel surface authority, `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` for companion-note semantics, or `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md` for topology rules.
Owner: Architecture / Companion UI product
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-05-24
Last verified against: docs/ARCHITECTURE.md, docs/COMPONENTS.md, docs/HUMAN-FLOWS.md, docs/FRONTMATTER.md, docs/EVENTS.md, docs/AGENTS.md, docs/AGENT_MEMORY/README.md, docs/CONTEXTUALIZATION_LAYER/README.md, docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md, docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md, docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md, docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md, docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md, docs/CONCEPTS/STATE_AXES_CONTRACT.md, docs/CAPABILITY_CONTRACT_MODEL.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md, companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md, governing issues #1251 and #1252.

# Vault Browser Capability Contract

> Audience: readers shaping how a human moves through, orients in, and returns to durable material in the vault. Read `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md` and `docs/HUMAN-FLOWS.md` first for the vault and human-flow vocabulary; this contract describes the **browser capability** that projects over those surfaces, not new artifact classes.

This contract names the long-term Vault Browser capability and the rules every implementation of it must satisfy. It does not introduce new event types, new database schemas, or new runtime authority. It does not move folders or rename artifacts. It defines the shape that current and future Vault Browser work must remain consistent with so the browser does not silently become a DB-first explorer, a hidden automation surface, or a graph-primary UI.

## 1. Purpose

The Vault Browser is the human-first **navigation and orientation surface** over the vault.

It is a projection over:

- vault files (Markdown notes, attachments)
- artifact metadata (frontmatter, identity, lifecycle, review posture, trust)
- relations between artifacts (links, citations, derivations, companions, projects)
- activity (creation, edits, reviews, indexing, agent activity, resurfacing)
- artifact health (frontmatter validity, broken links, staleness)
- provenance (origin, source reference, identity source)
- governed actions (read, ui-only, bounded system writes, governance writes, agent proposals, blocked)
- agent proposals (metadata fixes, summary updates, resurfacing candidates, relation suggestions)
- receipts (records of governed/system action over artifacts)

It is **not only** a file picker, **not** a graph view, **not** a search box, and **not** an execution surface. It is the human's continuous instrument for answering, on the vault: *where am I, what is this, why does it matter, where did it come from, what state is it in, can I trust it, what has the system done around it, and what is safe to do next.*

The Vault Browser is part of a **cognitive prosthetic** system. Its job is to reduce orientation cost and preserve human agency over a vault used over many years.

## 2. Human-first / cognitive prosthetic principles

The Vault Browser must:

- **Preserve human agency.** The human decides what to open, what to mark, what to act on. The browser surfaces, ranks, and explains; it does not auto-apply.
- **Reduce orientation cost.** Wherever possible, the browser answers "where am I, what is this, why does it matter" without forcing the human to open every artifact.
- **Support return-to-context after interruption.** A human returning days, weeks, or months later should be able to re-acquire context with minimum re-derivation.
- **Keep attention-state visible.** Active, semi-active, and peripheral material are not flattened to one list.
- **Support cognitive distance through zones.** Use `active`, `semi_active`, `peripheral` (and consistent zone language from `docs/HUMAN-FLOWS.md` / topology docs) as a stable cognitive-distance overlay. Zone is not maturity, not lifecycle state, and not folder.
- **Expose uncertainty and review posture.** Trust, review state, and health are first-class signals. Unreviewed and degraded material must not look identical to confirmed material.
- **Separate read, suggest, and write paths.** Browsing, proposing, and committing are different action classes. They are never collapsed into one click.
- **Avoid hidden automation.** Nothing happens to vault content because the human navigated to it. The browser may emit traces; it does not emit governed writes by being opened.
- **Prefer reversible and inspectable flows.** Every browser-initiated action is either read-only, UI-only, or routed through governed execution with a receipt.
- **Stay vault-driven.** Markdown/frontmatter is the human control surface. The browser reflects the vault; the vault is not reflected back into authority from the browser.

## 3. Relationship to system layers

The Vault Browser is a projection layer. It is not authority. Its relationship to the rest of the system is:

- **Vault / Markdown** is the human control surface and source of truth for human-authored content. The browser reads from it and surfaces its state. (`docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md`, `docs/FRONTMATTER.md`, `docs/CORE_CONTRACT.md`.)
- **Stores / DB / indexes** are machine mirrors. The browser may read from them for orientation, health, activity, and ranking, but they are never described as the authoritative artifact. (`docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`, `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`.)
- **Companion UI** is the human interaction surface that hosts the browser. The browser is one Companion UI surface among several (Workspace, Panel, Canvas, Chat). It is bounded by `docs/COMPANION_UI_PRODUCT_SPEC.md` and `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md`.
- **Agent Memory** is governed, non-authoritative unless promoted under policy. The browser may surface agent-derived signals (proposals, candidate relations, candidate resurfacing) but must mark them as such. (`docs/AGENT_MEMORY/README.md`, `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`.)
- **Contextualization Layer** provides artifact-class, use-right, and context framing. The browser respects these boundaries when projecting artifacts. (`docs/CONTEXTUALIZATION_LAYER/README.md`.)
- **Governance / authority boundary** decides what is read, what is bounded write, and what is governance write. The browser renders the server-declared classification of each action; it does not classify locally. (`docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`, `AGENTS.md` for builder governance.)
- **Events / outbox / receipts** are the traceability mechanism. The browser surfaces receipts when available; it does not invent a parallel record. (`docs/EVENTS.md`, `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`.)

The browser is a **read-and-orient** layer with explicit, narrow escape hatches into governed action. It is not allowed to become the place where store state becomes authoritative or where LLM output mutates notes.

## 4. Core concepts

The Vault Browser is defined by nine concepts. Implementations may extend them, but must not collapse them.

### 4.1 VaultArtifact

A durable artifact visible through the browser.

Required conceptual fields:

- `uuid` — artifact identity (frontmatter-rooted where applicable, see `docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md`)
- `path` — vault-relative path (POSIX)
- `title` — human-legible title (frontmatter `title` preferred, filename fallback)
- `kind` — artifact class (human note, companion note, attachment, system-surface artifact)
- `zone` — cognitive-distance overlay (`active`, `semi_active`, `peripheral`); see §2
- `review_state` — review posture (`docs/CONCEPTS/STATE_AXES_CONTRACT.md`)
- `trust` — trust tier (`assert` / `suggest` / `apply` per `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`)
- `origin` — provenance class (human-authored, agent-proposed, imported, mirrored)
- `source_ref` — pointer to the canonical source artifact when applicable (`docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`)
- `created`, `updated` — ISO-8601 timestamps

The artifact's authoritative state is in Markdown/frontmatter where it exists. The browser may carry projection fields beyond this list, but every projection must be reconstructible from vault + governed mirrors.

### 4.2 VaultView

A named projection over artifacts. Examples (capability map only; not all are MLP):

- `files` — file/folder enumeration (MLP-shaped)
- `artifacts` — typed artifact listing with metadata
- `review_queue` — artifacts in `needs_review` or equivalent posture
- `timeline` — chronological activity
- `graph` — relation-driven view (future, secondary)
- `source` / `evidence` — source artifact / citation view
- `agent_activity` — receipts and proposals view

Views are explicit and named. A view is never silently constructed by ranking heuristics.

### 4.3 VaultQuery

A structured, observable browsing/query contract.

Supported filter dimensions (capability map; subset shipped per MLP):

- text / path / title
- `kind`
- `zone`
- `review_state`
- `trust`
- `origin`
- `source_ref`
- `created` / `updated` range
- `health` state
- relation type
- receipt state

Ranking, when used, must be **explicit and observable**: the browser must be able to show which signals contributed to a result's position. Implicit semantic ranking without surfaced signals is out of scope. Deterministic filters (text, path, title) are preferred and required as the default.

### 4.4 VaultRelation

A relation between two artifacts.

Canonical relation types (capability map):

- `links_to`
- `cites`
- `derives_from`
- `companion_of`
- `belongs_to_project`
- `supersedes`
- `duplicates`
- `contradicts`
- `mentions`

Inferred or agent-proposed relations are **not equivalent** to human-confirmed relations. Implementations must mark provenance on each relation. Relation projections are read-only in the browser; promotion to durable vault-visible relations is a governance write (see §4.7).

### 4.5 VaultActivity

Time- and event-shaped facts needed for orientation.

Canonical activity kinds (capability map):

- `created`
- `edited`
- `reviewed`
- `indexed`
- `agent_proposed`
- `agent_blocked`
- `archived`
- `resurfaced`

Each activity entry should carry, when available: actor, timestamp, `trace_id` / `receipt_id`. Activity is a projection over the outbox/events stream (`docs/EVENTS.md`) and governed receipts; it is not a separate event source.

### 4.6 VaultHealth

Validation, decay, and degradation signals.

Canonical health classes (capability map):

- `frontmatter_valid`
- `missing_required_fields`
- `broken_links`
- `stale_summary`
- `stale_index`
- `unreviewed_generated_content`
- `trust_conflict`
- `blocked_write_state`

Health is descriptive; the browser surfaces it. It does not auto-repair from health signals.

### 4.7 VaultAction

A typed, governed action initiated from the browser.

Required fields per action:

- `id`
- `label` (human-legible)
- `scope` (artifact / selection / view)
- `mode` (see below)
- `requires_confirmation` (bool)
- `requires_receipt` (bool)
- `blocked_reason` or `disabled_reason` when not available

Required action modes (boundary contract):

- `read_only` — no state change anywhere (open, peek, copy path)
- `ui_only` — local Companion UI state only (toggle panel, expand row, change view)
- `bounded_system_write` — governed system-side state change with a receipt (mark indexed, queue for review)
- `governance_write` — change that crosses an authority boundary (alter review posture, alter trust, promote a relation, change lifecycle state) and must be routed through governed execution
- `agent_proposal` — surfaces an agent suggestion; never auto-applied
- `blocked` — currently unavailable; must include `blocked_reason`

The browser **renders the server-declared mode**. It does not reclassify modes locally. Body edits, governance edits, and agent proposals must never collapse into a single flow.

### 4.8 VaultProposal

An agent- or system-derived suggestion that may be shown in the browser but is never silently applied.

Canonical proposal kinds (capability map):

- `metadata_fix`
- `summary_update`
- `relation_add`
- `archive_candidate`
- `resurfacing`
- `duplicate_merge`

Required fields:

- `reason` (human-legible explanation)
- `evidence_refs` (pointers into artifacts / activity / health)
- `confidence` (when used; must be surfaced, not hidden)
- `status` (proposed / accepted / rejected / withdrawn)
- review posture (confirmed-by-human or not)

Proposals are a distinct artifact class from artifacts and from relations. They are subject to `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` and the trust contract.

### 4.9 VaultReceipt

A traceable record of a governed / system action over an artifact.

Required fields:

- `receipt_id`
- `action_id`
- `artifact_uuid` and/or `path`
- `requested_by` (human or agent)
- `approved_by` (human, where required)
- `trace_id`
- `status` (`ok`, `failure`, `degraded`)
- `timestamp`

Receipts are surfaced read-only in the browser. The browser does not author receipts; receipts come from governed execution (`docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`, `docs/EVENTS.md`).

## 5. Capability boundaries

The Vault Browser must keep the following capabilities **separate**:

- **Browsing** — enumerating, filtering, ranking, and visually presenting artifacts.
- **Retrieval** — answering a content/context question with ranked evidence (`docs/RETRIEVAL.md`).
- **Orientation** — surfacing "what is this, why does it matter, where did it come from, what state is it in" for a specific artifact.
- **Resurfacing** — bringing forgotten or dormant material back into attention under policy (`docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`, `companion-ui/docs/RESURFACING_HEURISTICS.md`).
- **Editing body content** — owned by Canvas / governed write paths, not by the browser.
- **Governance changes** — review-state / trust / lifecycle changes, routed through governed execution.
- **Agent proposals** — surfaced via `VaultProposal`, never auto-applied.

A Vault Browser implementation may compose with these capabilities, but must not collapse them into a single action.

## 6. MLP v0 boundary

The current shipped browser, referred to as **Vault Browser MLP v0**, is the baseline this contract aligns to. It is intentionally narrow.

Vault Browser MLP v0 provides:

- read-only enumeration of Markdown notes in the active vault
- a `read_only: true` invariant on the browser endpoint
- active vault/channel identity in the response payload (`vault_identity`, `identity_available`)
- deterministic case-insensitive path/title filtering via a single `q` parameter
- selecting a note loads it into the Companion workspace (read path only)
- exclusion of files outside the vault root
- explicit empty / error / identity-unavailable UI states with stable test IDs
- no mutation path from the browser surface; non-GET methods are rejected

Vault Browser MLP v0 explicitly does **not** provide:

- metadata-aware filters beyond text/path/title
- artifact inspector
- relation, activity, health, or receipt projections
- semantic / vector ranking
- governed actions, agent proposals, or receipts in-line
- graph, timeline, or saved views

MLP v0 is the stable contractual floor for later capability work. Subsequent slices add capabilities by extending the projection contract, not by altering MLP v0's invariants.

## 7. Future capability map

The following are **enabled but not implemented** by this contract. Each will be governed by a later issue/slice and is out of scope for #1251/#1252:

- metadata filters (kind, zone, review_state, trust, origin, source_ref)
- artifact inspector (metadata + provenance + health side panel)
- saved views
- review queue view
- timeline view
- relation / graph browsing
- semantic neighborhoods
- source / evidence browser
- agent activity / receipt explorer
- review campaigns
- resurfacing candidates view
- duplicate / contradiction detection surfaces
- long-term project resurrection workflow
- bulk operations with guardrails

These map onto the concepts in §4 and the capability boundaries in §5. None of them justify weakening the MLP boundary in §6.

## 8. Non-goals and anti-patterns

The Vault Browser is explicitly **not**:

- a DB-first browser (the vault and Markdown/frontmatter remain the human control surface)
- a replacement for Vault/Markdown authority
- a hidden automation surface (navigation never silently triggers governed writes)
- a graph-first UI (graph is one optional future view, not the primary navigation model)
- a generic Obsidian clone (the goal is governed cognitive prosthesis, not a re-implementation of a file explorer)
- a place where AI suggestions mutate notes directly (no LLM-mediated mutation without governance, guardrails, and receipts)
- a place where body edits, governance edits, and agent proposals are collapsed into one flow

Anti-patterns to refuse in implementation:

- treating store/DB state as authoritative when the vault disagrees
- collapsing `read_only`, `ui_only`, and `bounded_system_write` into a single "click"
- inventing a parallel receipt or activity record outside the governed event/outbox stream
- ranking without surfaced signals
- silently expanding scope from "browse" to "act"

## 9. Degraded / blocked / error states

Every Vault Browser implementation must define behavior for the following classes:

- **vault identity unavailable** — `identity_available: false`; browser must distinguish this from "empty"
- **artifact metadata invalid** — the artifact is surfaced with explicit invalid-metadata health, not hidden
- **frontmatter missing / invalid** — same: surfaced with health, not silently corrected
- **WriteGuard blocked / safe_mode / degraded / unhealthy** — actions are rendered with `mode=blocked` and a `blocked_reason`
- **receipt source unavailable** — receipts are absent rather than fabricated
- **relation index unavailable** — relation projections degrade explicitly (empty + reason), not silently
- **no matches** — distinct from "no notes"
- **API error** — distinct from "empty" and "identity unavailable"

The browser surface must make degradation legible. Silent degradation is a contract violation.

## 10. Implementation and test guidance

For future implementation issues, this contract requires:

- The server/runtime owns vault enumeration and metadata normalization. Clients render server-declared state and server-declared action modes.
- Deterministic filters (text/path/title) are the default. Any added ranking must surface its signals.
- The browser endpoint must remain read-only in the HTTP sense at the MLP v0 boundary (no mutating verbs accepted on the browser route).
- UI states (`empty`, `error`, `identity-unavailable`, future `degraded`/`blocked`) must have stable test IDs / data attributes so contract tests can assert them.
- Read-only contract tests must assert that calling the browser endpoint does not mutate any vault file.
- Docs must be updated in the same change as shipped behavior changes (per `AGENTS.md` required rules).
- New event types are not expected for browser work. If a future slice introduces one, `docs/EVENTS.md` must be updated in the same change (per `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md`).

## 11. Relationship to current shipped behavior

The currently shipped Companion UI vault browser (from #1225 / PR #1239 and follow-ups) is the canonical realization of `Vault Browser MLP v0` as defined in §6. Alignment work for that baseline is tracked under #1252. Subsequent slices that introduce metadata, inspector, governed action, or receipt behavior extend this contract without weakening §6 or §8.

**#1253 (normalized metadata read model):** The vault browser API response now includes normalized artifact metadata per note: `uuid`, `kind`, `zone` (frontmatter-preferred, path-derived fallback), `review_state`, `trust`, `origin`, `source_ref`, `created`, `updated`, `frontmatter_valid`, and `missing_required_fields`. Frontmatter is parsed server-side; clients never receive raw YAML. Missing or invalid frontmatter surfaces as explicit health state (`frontmatter_valid: false`), not a crash. Basic metadata badges (`kind`, `review_state`, `trust`) and health warnings render in the browser list view when present. This is an enabling change for §4.1 (`VaultArtifact` fields) without introducing filters (§4.3), inspector (§4.4+), or actions (§4.7) — those remain in subsequent slices.

**#1254 (deterministic metadata filters and badges):** The vault browser API now accepts deterministic server-side filter query params: `kind`, `zone`, `review_state`, `trust` (each multi-value, e.g. `?kind=human_note&kind=companion_note`). Active filters are returned in `active_filters` and composed with the existing `q` text search (AND semantics). Notes with a missing field value for an active filter are excluded. Filter chips are rendered in the Companion UI with `data-testid="vault-browser-filter-chip"`, `data-key`, `data-value`, `data-active` attributes. No opaque ranking or hidden heuristics. This enables §4.3 (`VaultQuery`) filter dimensions without introducing inspector, actions, or receipts.

**#1255 (read-only artifact inspector panel):** When a vault browser result matches the active workspace note, the Companion UI renders an artifact inspector panel (`data-testid="workspace-vault-browser-inspector"`). The inspector is read-only and exposes no edit or write controls. It renders: title, path, uuid (if present), kind, zone, review_state, trust, origin, source_ref, created, updated from the normalized server payload; a health section (`data-testid="workspace-vault-browser-inspector-health"`) with `data-health-state="valid|invalid"` visible unconditionally (not hidden); separate artifact identity and vault/channel identity surfaces (`data-testid="workspace-vault-browser-inspector-artifact-identity"` and `"workspace-vault-browser-inspector-vault-identity"`); and explicit `not connected yet` placeholders for links (`data-testid="workspace-vault-browser-inspector-links-placeholder"`) and agent receipts (`data-testid="workspace-vault-browser-inspector-receipts-placeholder"`). Client uses only the normalized server payload — no frontmatter parsing in the client. This enables §4.4+ (inspector) without introducing VaultAction modes (§4.7) or receipt lookup (§4.8).

**#1256 (VaultAction display model):** The artifact inspector now includes a `VaultAction` display strip (`data-testid="workspace-vault-browser-inspector-actions"`). Each action carries: `data-mode` (action class: `read_only`, `ui_only`, `bounded_system_write`, `governance_write`, `agent_proposal`, `blocked`), `data-affordance-status`, and optionally `data-blocked="true"` + `data-blocked-reason`, `data-requires-receipt="true"`, `data-requires-confirmation="true"`. Shipped initial actions: `open_note` (read_only), `copy_path` (ui_only), `find_related` (read_only, disabled with reason), `queue_review` (governance_write, blocked with reason + requires-receipt + requires-confirmation). No new write path is opened — governance/write actions are blocked with explicit reasons in this slice. The body update flow remains separate from the browser action model. This establishes the action-class boundary from §4.7 without implementing write execution.

**#1281 (wire open_note + copy_path affordances):** Delivered by PR #1320 (2026-05-26). The `open_note` (`read_only`) and `copy_path` (`ui_only`) actions now carry `data-affordance-status="available"`. `open_note` is wired with `data-href="?note_path=<vault-relative-path>"` and `onclick="window.location.href=this.dataset.href"` — same-origin navigation, no new API endpoint, no write path. `copy_path` is wired with `data-path="<vault-relative-path>"` and `onclick="navigator.clipboard.writeText(this.dataset.path)"` — client-side only, no vault mutation. Both remain in their declared action modes; no mode classification changed. `data-*` attributes expose values for test verification without JS execution.

**#1257 (agent receipts and review posture):** The artifact inspector renders a receipt/posture section (`data-testid="workspace-vault-browser-inspector-receipts"`). Receipt state is determined from the note payload's `receipts` field: absent key → `data-receipt-state="unavailable"` (source not connected, honest placeholder); empty list → `data-receipt-state="no_receipts"` (source connected, none found); non-empty → renders each receipt row with `data-testid="vault-browser-receipt-row"`, `data-receipt-state`, `data-testid="vault-browser-receipt-id"`, and `data-testid="vault-browser-receipt-trace-id"` kept separate from artifact identity. Review posture (`data-testid="workspace-vault-browser-inspector-review-posture"`) surfaces `review_state` and `trust` from the normalized metadata with `data-review-authority="non_authoritative"` — unreviewed/inferred memory is explicitly labeled and does not become action-authorizing. No mutation controls rendered. Supported receipt states: `queued`, `applied`, `blocked`, `rejected`, `failed`. Current API does not yet populate receipts → renders `unavailable` honestly; wiring the receipt source is a future follow-up.

**#1280 (wire interactive filter chip clicks):** Delivered by PR #1322 (2026-05-26). Filter chips now carry `onclick="vbToggleFilter(this)"` and `style="cursor:pointer"` — clicking an inactive chip appends its `data-key`/`data-value` to the URL query string and reloads; clicking an active chip removes it. When multiple values are active for the same dimension, each chip renders a deselect affordance (`data-testid="filter-chip-remove"` `×` span); a single active chip shows no affordance. The `handle_get` handler parses `kind`, `zone`, `review_state`, `trust` from the query string and forwards them to the vault-browser API, making active filter state bookmarkable. Server remains the authoritative filter processor; no client-side filtering is introduced. Extends §4.3 (`VaultQuery`) interactive capability without altering filter semantics.

**#1283 (visually distinguish companion vs human notes):** Delivered by PR #1323 (2026-05-26). Browser list rows with `kind=companion_note` carry three additional attributes: `data-companion="true"`, `data-kind="companion_note"`, and CSS class `vault-browser-row--companion`. The kind match uses an exact frozenset lookup (`_COMPANION_KINDS = frozenset({"companion_note"})`) — no substring heuristics. The inspector panel similarly carries these attributes when the active note is a companion. Human note rows carry none of these attributes. No new kind classification is introduced; the treatment is driven entirely by the server-declared `kind` field from the normalized metadata payload. Extends §4.1 (`VaultArtifact`) visual treatment without altering companion note semantics or introducing new API fields.
