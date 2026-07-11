---
name: mimer-vault-workspace
description: "External app-agent client skill for the live vault filesystem (product lane; NOT for dev/build work in this repo — the repo's vault/ is a fixture, not a real vault): direct-filesystem participation (AGENT-FLOWS mode c) when the human, as a Mimer user, points the agent at vault material to draft, synthesize, or edit. Full write discipline applies."
---

# Mimer Vault Workspace

Product-lane client skill; not a Builder System workflow — for dev work in this repo use the
builder skills per `.codex/skills/README.md`.

Governed by `docs/contracts/MIMER_CLIENT_CONTRACT.md` §5-§6 and `docs/AGENT-FLOWS.md` §3/§4/§7
(mode c, observed-write semantics). Read `.codex/skills/mimer-governed-boundary/SKILL.md` first —
its exclusion list and provenance block bind every write this skill makes.

## When to use

The human has pointed the agent at the vault filesystem for drafting, synthesis, or editing a
specific note — a working session, not a one-shot capture or a query. This is a direct-filesystem
write, distinct from the governed API path `mimer-capture` uses.

## Where this skill may write

- **Declared workspace roots** (AGENT-FLOWS §7: knowledge-base root, synthesis/index root,
  draft/workspace root) are the default write surface. The Sources zone is excluded even where it
  would otherwise resemble a source/evidence root. Output here lands at draft-zone standing —
  observed, classified, never auto-canonical, regardless of content quality.
- **Human-directed edits to any vault note outside the Sources zone**, when the human directs the
  edit in the live session.
  This is exactly the surface where a collision destroys human-authored prose — apply the full
  write discipline below without exception.

An observed write is not APPLY, produces no Mimer receipt, and confers no authority on its own. It
becomes human-canonical only when the human promotes it through their own review path.

## Exclusions

Never direct-write the capture inbox, Sources zone, companion notes, system-plane files, or the
`_heimdal` control tree — see `.codex/skills/mimer-governed-boundary/SKILL.md`'s exclusion list.
If the human asks to write into one of these, decline and redirect: inbox content goes through
`mimer-capture`; Sources is Heimdal-side sensor/acquisition-only; the rest are runtime- or
Bifrost-owned.

## Write discipline (contract §6)

- **Prefer governed append for durable intake.** Anything shaped like "remember/capture this"
  goes through `mimer-capture`, not a direct write here, even mid-session.
- **Read-fresh, verify-staleness.** Before any whole-file write: read the file and record its
  content hash; keep the read-to-write window short; re-check the hash immediately before
  writing. If the file changed since the read, re-read and re-apply the edit on the new content —
  never write the stale version. This is advisory, not atomic: the check-to-write window is real
  and a concurrent writer can still land inside it (the residual risk stays open until
  ADR-0055's substrate mechanism is enacted) — the procedure shrinks collision risk, it does not
  eliminate it, which is why it matters most on human-authored prose.
- **Ownership courtesy.** Default to files the agent itself authored. Edit a human-authored note
  only on explicit human direction in the live session; prefer append/patch-shaped edits over
  whole-file rewrites of prose the human may have open in Obsidian.
- **Atomic replace.** Whole-file writes land as write-to-temp-then-rename in the same directory.
  Never leave temp files behind on failure.
- **Verify, don't blind-retry.** After a timeout or a lost response, verify by reading the target
  before retrying. Whole-file writes are idempotent by content; appends are not — check for the
  marker/line before re-appending.
- **Don't fight the watcher.** The file is truth; the search index is eventually consistent. Never
  re-write a file to "fix" perceived index lag.
- **One transport per note.** The capture inbox is excluded from filesystem writes precisely so
  the two transports never collide on it. If a same-note collision is nonetheless suspected,
  report it to the human with both versions' evidence rather than silently re-asserting one.
  Know what is authoritative for what: the file's current content is the outcome
  (last-write-wins), while any AuthorityReceipt/outbox event remains the truthful record of what
  a governed write did *at its time* — receipts are authoritative for what happened, never for
  what is currently true, so never "correct" a file to match a receipt.
- **iCloud conflict artifacts.** Never merge, delete, or adopt a "conflicted copy" sibling
  silently — surface it to the human.

## Provenance

Every file this skill **creates** MUST carry the provenance frontmatter block from
`.codex/skills/mimer-governed-boundary/SKILL.md`; every substantive edit to an existing note
SHOULD append to it.

## Failure handling

Check `GET /healthz` (or `/api/status`) before entering a write flow (contract §7). If the API
is unreachable, **degrade to read-only** over the declared filesystem roots and say so (contract
§6 degradation table): an unreachable runtime means the watcher/ingest side may be down too, so
no new direct-FS writes until health returns — and never a shadow write queue that replays into
the vault later without the human. If a same-note collision is suspected, follow the
one-transport-per-note rule above.

## Authority limits

- No lifecycle/frontmatter mutation of a human note beyond what the human directed.
- No promotion of workspace drafts to canonical standing — that is the human's act.
- No writes to the `_heimdal` tree, companion notes, system-plane files, the capture inbox, or the
  Sources zone, ever.

## References

- `docs/contracts/MIMER_CLIENT_CONTRACT.md` §5, §6.
- `docs/AGENT-FLOWS.md` §3/§4/§7.
- `.codex/skills/mimer-governed-boundary/SKILL.md`.
