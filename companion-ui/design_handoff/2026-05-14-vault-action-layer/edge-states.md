# Edge states — Vault Action Layer

Per the governance pack §08 checklist. Full visual treatment in **`prototype.html` §07**.

- **Empty** — no action invoked; surface shows the action registry doc entry.
- **Loading** — pipeline steps populate progressively, but the trace shape does not jump.
- **Degraded** — if the outbox is degraded, step 09 emits a deferred-event receipt; the
  action still succeeded.
- **Blocked** — write guard refusal at step 05; auditable; never silently retried.
- **Stale** — source note edited since the panel turn; step 03 refuses with
  `source.stale`.
- **Missing provenance** — source note without frontmatter; step 03 refuses with
  `type.unknown`.
- **Write-guard denial** — see Blocked above; rendered as state 04 in the gallery.
- **Reduced motion** — trace lines are static; no sequential animation; state legible from
  colour and copy.
- **Narrow / mobile** — action stage stacks vertically; gallery is one column.

## Deferred-with-reason

None.
