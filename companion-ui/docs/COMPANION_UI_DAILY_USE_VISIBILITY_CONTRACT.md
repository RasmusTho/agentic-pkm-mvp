# Companion UI Daily-Use Visibility Contract

**Status:** Shipped — dev/staging only  
**Baseline:** `codex/companion-daily-use-visibility-contract`  
**Governing issue:** #1361

---

## Purpose

This contract defines which UI elements are always visible, which are hidden behind disclosure,
and which are suppressed when disabled or irrelevant. It ensures the Companion UI reads as a
cognitive reading surface rather than a dev/UAT harness during daily use.

This is a visibility contract, not a rendering contract. It governs information hierarchy and
chrome density, not Markdown rendering fidelity (see `VAULT_MARKDOWN_RENDERER_CONTRACT.md`).

---

## Section A — Header chrome / operator controls

### Rule: Dev controls behind disclosure

The operator controls (API URL, note_path input, Load button, Browse vault button) are wrapped
in a `<details class="dev-controls-disclosure">` element (`data-testid="workspace-dev-controls"`).

- The disclosure is **open by default** in dev so existing workflows are not disrupted.
- Collapsing it is persistent until the page reloads (native `<details>` behavior).
- The toggle label is "DEV · operator" (`data-testid="workspace-dev-controls-toggle"`).

### Rule: Runtime channel identity always visible

The runtime safety strip (`data-testid="workspace-runtime-safety-strip"`) is always visible
outside the dev-controls disclosure. It contains:
- `data-testid="workspace-runtime-channel"` — vault channel identifier
- `data-testid="workspace-runtime-trace-id"` — request trace ID
- `data-testid="workspace-runtime-environment"` — environment label (dev/prod)

This strip is wrapped in a `<details class="runtime-telemetry-disclosure">` (open by default
in dev) but the safety strip content is always rendered — collapsing the disclosure hides the
detailed strip lines from view but not from DOM.

The runtime-channel element must not appear inside the dev-controls disclosure content.

---

## Section B — Panel visual states: disabled/degraded suppression

### Rule: Duplicate disabled surfaces suppressed

When the Canvas session is disabled (`guard_canvas_enabled=false`), the
`canvas-body-edit-unavailable` element is rendered with `hidden` attribute and the modifier
class `canvas-body-edit-unavailable--suppressed`. This prevents a visible "Body editing
unavailable" banner from appearing alongside the guard alert that already communicates the
blocked state.

`data-testid="workspace-canvas-body-edit-unavailable"` is always present in DOM (for test
compatibility) but hidden when suppressed.

### Rule: Active-note-body-update blocked state suppressed when disabled

When `active_note_body_update_enabled=false` (defaults to `guard_workspace_update_available`),
the blocked state element (`data-testid="workspace-active-note-body-update-state-blocked"`) is
rendered with `hidden`. The outer section carries `data-flow-state="disabled"` for automation.

---

## Section C — Vault browser: filtering and calm provenance

### Rule: Companion and UUID notes hidden from navigation list

The vault browser navigation list (`data-testid="workspace-vault-browser-list"`) filters out:

1. Notes with `kind == "companion_note"` — system-generated companion metadata files.
2. Notes whose filename stem (before `.md`) matches the UUID pattern
   `[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`.

These notes are hidden for daily-use navigation. The count of hidden notes is shown as
`data-testid="workspace-vault-browser-hidden-count"` with `data-hidden=N` when `N > 0`.
The element is absent when nothing is filtered.

### Rule: Per-note metadata badges visually hidden in nav list

Kind, review-state, and trust badges on each note row carry
`class="note-badge note-badge--nav-hidden"` and `data-nav-visible="false"`. CSS sets
`.note-badge--nav-hidden { display: none; }`.

The inspector panel (right rail) shows the full metadata for the selected note.
The `data-testid` attributes are retained for test and automation compatibility.

### Rule: Calm provenance label

The vault browser provenance element (`data-testid="workspace-vault-browser-provenance"`)
shows a calm human label:
- `read_only=true` → `"read-only fallback · filesystem index"`
- `read_only=false` → `"filesystem index"`

The raw `vault_provenance` value from the API is retained in `data-raw-provenance` for
debugging and test assertions.

---

## Section D — Read-only body affordance

### Rule: Note body always carries read-only indicator

The note body div (`data-testid="workspace-note-body"`) carries `data-read-only="true"`.

A calm, low-noise read-only indicator (`data-testid="workspace-note-body-readonly-indicator"`)
is always rendered in the note body area when the body is read-only. It uses small monospace
uppercase text styled with `color: var(--fg-3)`.

### Rule: Inline reason with Why? link on focus/click

The read-only reason element (`data-testid="workspace-note-body-readonly-reason"`) is always
present in DOM with `hidden` attribute. It becomes visible on focus/click (CSS `:focus-within`
or JS interaction — see serve_dev_page.py implementation).

The reason text contains a "Why?" link (`data-testid="workspace-note-body-readonly-why"`)
that links to `#workspace-runtime-telemetry`, which anchors to the runtime telemetry
disclosure in the note section. This lets users navigate from the note body directly to the
runtime state that explains why editing is disabled.

### Governance constraint

The note body must not become editable through this affordance. Any future edit capability
must route through the Canvas body-edit API (`POST /api/canvas/sessions/{id}/edits`),
not through direct vault writes. See `CANVAS_SUGGESTION_FLOW.md`.

---

## Section E — Breadcrumb / properties humanization

### Rule: Frontmatter behind disclosure with humanized summary

When a note body contains YAML frontmatter (delimited by `---`), the frontmatter section
(`data-testid="workspace-note-frontmatter"`) renders as a `<details>` element
(`data-testid="workspace-frontmatter-disclosure"`).

The `<summary>` (`data-testid="workspace-frontmatter-summary"`) shows human-readable labels
for recognized keys, produced by `_humanize_fm_pair(key, value)`:

| Frontmatter key | Raw value | Human label |
|---|---|---|
| `review_state` | `needs_review` | `review · needs review` |
| `review_state` | `reviewed` | `review · reviewed` |
| `lifecycle_state` | `active` | `lifecycle · active` |
| `note_type` or `kind` | `human_note` | `type · note` |
| `note_type` or `kind` | `companion_note` | `type · companion` |
| `zone` | `active_zone` | `zone · active zone` |

Unknown keys return `None` from `_humanize_fm_pair` and are excluded from the summary.
Raw snake_case values must not appear in the summary text.

The disclosure body still shows the raw YAML lines as `<code>` elements for operator use.

---

## What this contract does NOT cover

- Mermaid rendering failures — see `VAULT_MARKDOWN_RENDERER_CONTRACT.md` error states.
- Wikilink resolution failures — same.
- Panel/Canvas write boundaries — see `PANEL_COMPANION_UI_CONTRACT.md` and `CANVAS_SUGGESTION_FLOW.md`.
- Production UI framework decisions — deferred; current implementation is Python/Jinja2 + Tailwind.
- Auth, TLS, reverse proxy — deferred; dev-only surface.
