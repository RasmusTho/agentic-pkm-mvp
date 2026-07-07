---
name: mimer-retrieve
description: "Read-only vault search — use when the human asks what do I have on X / find my notes about Y. Search then note-read, with filesystem enrichment as the sanctioned uuid-to-path fallback. Never a write."
---

# Mimer Retrieve

Product-lane client skill; not a Builder System workflow — for dev work in this repo use the
builder skills per `.codex/skills/README.md`.

Governed by `docs/contracts/MIMER_CLIENT_CONTRACT.md` §4.2. Read
`.codex/skills/mimer-governed-boundary/SKILL.md` first.

## When to use

The human wants to find existing material: "what do I have on X", "find my notes about Y", "do I
have anything on Z", "pull up my notes on...". Read-only, no vault mutation of any kind.

Not this skill: a question the vault should answer with a synthesized response (`mimer-ask`), a
capture request (`mimer-capture`), or drafting/editing a specific note (`mimer-vault-workspace`).

## Operation

1. `GET /search?q=<query>` — returns a fixed-size list (k=10) of `{uuid, title}` pairs. That is
   the whole result shape; do not expect a body or a path back from this call.
2. To read a hit's content: `GET /api/artifacts/note?note_path=<vault-relative path>`. The
   response carries `artifact_id`, `note_path`, `title`, `body`, `content_hash` — **the
   `note_path` field in the response is the absolute resolved filesystem path**, not the
   vault-relative path the request used. Never store or echo this absolute path back to the human
   or to another host; treat it as call-scoped.

## The uuid-to-path gap (contract §4.2)

Search returns *uuid*; note-fetch keys by *path*; no endpoint resolves uuid to path today (named
follow-on work, contract §9 F3). The sanctioned v1 posture:

- Prefer `mimer-ask` when a synthesized, cited answer will do — its sources carry `path` directly.
- When a raw note body behind a search hit is genuinely needed, filesystem-read enrichment within
  the human's declared workspace/vault roots (matching the search hit's uuid against the
  frontmatter `uuid` field of candidate files) is the sanctioned fallback.
- Never invent or persist a private uuid-to-path index and treat it as authoritative — that is
  exactly the hidden-source-of-truth invariant this family exists to hold (see
  mimer-governed-boundary).

## Presenting results

- Cite results by title and (when read) path — the human should be able to tell what stood behind
  an answer.
- **Never present a retrieval miss as absence of knowledge.** The index is a rebuildable
  projection that trails the vault (watcher → ingest → index); a miss can mean "not indexed yet,"
  not "doesn't exist." Say so when a search comes back empty or thin, especially right after a
  recent capture.
- Never assume read-your-write: a capture just made via `mimer-capture` may not appear in search
  results immediately.

## Failure handling

A retrieval failure propagates as an error — no silent filler content, no fabricated result set.
Surface the error and stop.

## Authority limits

- Strictly read-only. No write follow-up without the human separately invoking `mimer-capture` or
  `mimer-vault-workspace`.
- No promotion, no reclassification, no editing of anything returned.

## References

- `docs/contracts/MIMER_CLIENT_CONTRACT.md` §4.2, §6 write discipline item 6.
- `.codex/skills/mimer-governed-boundary/SKILL.md`.
