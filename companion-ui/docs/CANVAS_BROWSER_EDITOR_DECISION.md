---
name: Canvas Browser Editor Decision
description: Decision record for the browser editor primitive and edit delivery model used by Canvas browser integration
doc_role: Decision record / implementation gate
authority: Binding decision for Canvas browser editor integration until superseded by a later accepted decision.
owner: Companion UI / Canvas integration
last_reviewed: 2026-05-19
source_contracts:
  - companion-ui/docs/WORKSPACE_STATE_CONTRACT.md
  - companion-ui/docs/CANVAS_AGENT_MVP_CONTRACT.md
  - companion-ui/docs/CANVAS_SUGGESTION_FLOW.md
  - companion-ui/companion-app/companion_ui/canvas_core/session_state.py
  - companion-ui/companion-app/companion_ui/canvas_core/undo_stack.py
  - app/api/routes/canvas.py
governing_issue: "#1126"
---

# Canvas Browser Editor Decision

## Decision

Use a native `textarea` as the interim Canvas browser editor primitive.

The browser integration will edit Markdown source directly and submit the full
note body through the existing Canvas body-edit lane. No CodeMirror,
ProseMirror, rich-text editor, or rendered-markdown/source split is introduced
in this slice.

## Rationale

The shipped Canvas API and Canvas Core model are already shaped around direct
body replacement for the currently open artifact:

- The browser loads the full note body from the workspace aggregate.
- The Canvas edit path accepts a replacement body (`new_body`) plus a change
  summary.
- Canvas Core permits only body edits on the direct co-authoring path.
- Governance-bearing or ambiguous mutations must route through the escape
  hatch/Panel path, not through the body editor.

A `textarea` matches that model with the least extra state:

- Markdown source is the canonical editing representation for this interim
  browser slice.
- No editor dependency is added before richer UX requirements are proven.
- Full-body replacement is simple to reason about and test.
- Replacement with a richer editor remains possible later because this decision
  does not define a persistent editor document model.

## Rejected Options

| Option | Reason rejected for this slice |
|---|---|
| CodeMirror | Reasonable future option, but adds a dependency and editor state model before the first browser integration proves the full-body flow. |
| ProseMirror | Too much document-model complexity for a Markdown body replacement API. Would require serialization decisions that are not needed now. |
| Rendered markdown plus source editor toggle | Useful later, but introduces two synchronized views before the edit/conflict path is proven. |

## Edit Delivery

Canvas browser edits use full-body replacement.

The browser flow is:

1. Load `artifact.body` and `artifact.content_hash` from
   `GET /api/companion/workspace`.
2. Let the user and assistant edit the Markdown body in the `textarea`.
3. Before submit, compare the current workspace baseline to the latest known
   `content_hash` if the implementation has refreshed state.
4. Submit `new_body` and `change_summary` through the Canvas edit path.
5. On success, refresh workspace state and replace the local baseline.

The browser integration must not invent a patch/delta protocol in this slice.
If patch-based edits become necessary, they require a separate API contract
change before implementation.

### Hash Check Implication

`WORKSPACE_STATE_CONTRACT.md` exposes `artifact.content_hash` as the browser's
stale-read baseline. Browser implementation must use that value to avoid
overwriting external changes silently.

If the runtime edit endpoint does not yet accept an explicit content-hash
precondition, the implementation issue must add that precondition or perform an
equivalent runtime-side stale-read check before applying the full-body
replacement. Silent last-write-wins behavior is not acceptable for the browser
Canvas editor.

## Conflict Behavior

### Content Hash Mismatch

When the browser's baseline hash does not match the runtime's current body
hash, the submit is stale.

Required behavior:

- Do not submit or apply the replacement body silently.
- Surface a conflict state in the browser.
- Offer an explicit refresh/reload path that preserves the user's unsent draft
  locally until the user decides what to do.
- Require a new user action before retrying against the refreshed baseline.

### Paused or Interrupted Session

When `canvas.session_state` is `paused` or `interrupted`:

- Body editing is disabled.
- The browser renders recovery-needed state from
  `canvas.recovery_needed = true`.
- Resume/recover must be explicit before body edits can submit.

### External Obsidian Edit

An external Obsidian edit is detected as a content-hash delta between the
loaded baseline and the current runtime state.

Required behavior is the same as content hash mismatch: no silent overwrite,
visible conflict state, explicit refresh/retry.

## Undo Granularity

Use last-assistant-edit undo only for the interim browser slice.

This matches the shipped Canvas undo stack, which is session-scoped,
artifact-scoped, and reverts the most recent assistant-applied body edit when
the current body still matches the post-edit body. Stack-wide or arbitrary
multi-step browser undo is out of scope for this decision.

User keystroke undo remains the browser/editor's local responsibility. Canvas
assistant undo remains the runtime/session responsibility.

## Implementation Gate

Issues #1126-#1129 (Canvas browser integration) are blocked until this
decision doc is accepted.

Any later move to CodeMirror, ProseMirror, a rendered/source split, streaming
edits, or patch-based delivery must be recorded in a replacement decision
before implementation.
