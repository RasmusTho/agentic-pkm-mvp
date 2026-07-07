---
name: mimer-ask
description: "External app-agent client skill operating a running Mimer host (product lane; NOT for dev/build work in this repo): grounded Q&A over the vault with per-source citations when the human, as a Mimer user, asks a question their vault should answer. Never blends the agent's own knowledge in unmarked; no write follow-up without an explicit capture request."
---

# Mimer Ask

Product-lane client skill; not a Builder System workflow — for dev work in this repo use the
builder skills per `.codex/skills/README.md`.

Governed by `docs/contracts/MIMER_CLIENT_CONTRACT.md` §4. Read
`.codex/skills/mimer-governed-boundary/SKILL.md` first.

## When to use

The human asks a question they expect the vault's own material to answer: "what did I decide
about X", "why did I...", "summarize what I know about Y". Read-only.

Not this skill: a bare lookup/find request (`mimer-retrieve`), a capture request
(`mimer-capture`), or an edit to a specific note (`mimer-vault-workspace`).

## Operation

`POST /api/ask` with `{"question": "<question>"}` (the field alias `query` and an optional
`zone_strategy` are also accepted). Send an `X-Trace-Id` header.

The response carries an answer plus per-source attribution — each source carries `uuid`, `title`,
`origin`, `plane`, `zone`, and `path`.

## Presenting the answer

- Cite sources per the response's attribution — title and origin/zone at minimum, so the human
  can tell what grounded the answer.
- **Never blend the agent's own outside knowledge into the answer without marking it as such.** If
  the vault's material is thin and general knowledge would fill the gap, say so explicitly and
  keep the two visibly separate — don't let ungrounded content read as vault-grounded.
- If the vault has nothing relevant, say that plainly rather than answering from the agent's own
  training.

## No unsolicited write follow-up

Answering a question is never itself a reason to write to the vault. If the human's answer implies
something worth capturing ("oh, I should remember that"), name the option and wait for the human
to actually ask for it — do not chain automatically into `mimer-capture`.

## Failure handling

An ask failure propagates; never answer from the agent's own knowledge while implying vault
grounding it doesn't have.

## Authority limits

- Strictly read-only.
- No promotion of the answer or its sources into any other surface.

## References

- `docs/contracts/MIMER_CLIENT_CONTRACT.md` §4.
- `.codex/skills/mimer-governed-boundary/SKILL.md`.
