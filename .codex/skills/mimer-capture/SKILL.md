---
name: mimer-capture
description: "External app-agent client skill operating a running Mimer host (product lane; NOT for dev/build work in this repo): friction-free intake into the vault inbox when the human, as a Mimer user, says capture/remember/add to my inbox/jot this down. Governed write via the capture endpoint; never composes frontmatter or picks a target note."
---

# Mimer Capture

Product-lane client skill; not a Builder System workflow — for dev work in this repo use the
builder skills per `.codex/skills/README.md`.

Governed by `docs/contracts/MIMER_CLIENT_CONTRACT.md` §4.1. Read
`.codex/skills/mimer-governed-boundary/SKILL.md` first — the invariants, error-surfacing duties,
and never-degrade rule bind this skill.

## When to use

The human expresses intent to capture a thought, commitment, or note into their vault: "remember
this", "capture that", "add to my inbox", "jot this down", "note that for later". This is the
**only** mimer-* skill that performs a durable write to the vault via the governed API path.

Not this skill: a request to find or recall something (`mimer-retrieve`), a question the vault
should answer (`mimer-ask`), or a request to draft/edit a specific note the human is pointing at
(`mimer-vault-workspace`).

## Operation

Check `GET /healthz` (or `/api/status`) before entering the write flow (contract §7); if the
runtime is unhealthy, surface that instead of writing.

Call `POST /api/companion/capture` with a body of exactly `{"text": "<non-empty string>"}` — the
schema forbids extra fields, so do not add anything else (no provenance field, no due date, no
tags — the endpoint rejects extras with 422). Send an `X-Trace-Id` header.

The write is an append-only timestamped bullet to the vault inbox note. This skill:

- **never composes frontmatter** — the append target and shape are entirely runtime-owned;
- **never picks the target note** — there is exactly one target, the inbox note, resolved by the
  runtime;
- **never chunks, edits, or reformats** the human's words before sending them — pass the text
  through as given. Light cleanup of transcription artifacts is fine; adding structure, tags, or
  interpretation the human didn't say is not.

## Success

On success, the response carries `outcome`, `note_path`, `operation`, `adapter`, `captured_at`,
`trace_id`, `events_emitted`, `governed_write`, and `ingest_warning`. Surface the `governed_write`
receipt (the PolicyDecision/DecisionToken/AuthorityReceipt) to the human as confirmation — do not
fabricate acknowledgement wording that implies more or less than what the receipt says. If
`ingest_warning` is set, say so: the capture is durable, but the search index may lag behind it.

## Failure handling

Per the contract's §4.1 error contract — handle each named state, never retry blindly:

| Status | State | Action |
| --- | --- | --- |
| 422 | Schema error / empty capture | Nothing written. Fix the request, or tell the human the text was empty. |
| 409 | WriteGuard-blocked | Nothing written. Surface the reason verbatim. Never fall back to a direct filesystem write (mimer-governed-boundary's never-degrade rule). |
| 409 | Inbox-convention-unresolved | Nothing written. Surface to the human. |
| — | Vault-selection-required (matched on the response's `state` field) | No active vault. The human selects one — never guess. |
| 500 | Not-acknowledged | The append **may have landed**. Do NOT blind-retry (duplicate-append risk). Verify by reading the inbox note tail before deciding whether to retry or hand to the human. |

## Authority limits

- Text-only append to the inbox. No note creation, no editing of existing notes, no frontmatter,
  no tagging, no promotion.
- No fallback to a direct filesystem write on any blocked or degraded state
  (mimer-governed-boundary).
- No egress beyond what the human explicitly asked to capture — do not append inferred or
  embellished content.

## References

- `docs/contracts/MIMER_CLIENT_CONTRACT.md` §4.1, §6 write discipline items 1 and 5.
- `.codex/skills/mimer-governed-boundary/SKILL.md`.
