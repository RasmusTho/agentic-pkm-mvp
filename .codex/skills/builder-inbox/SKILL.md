---
name: builder-inbox
description: "Read bounded Builder Thread inbox projections through the designated serialized BuilderOps writer without mutation."
---

# Builder Inbox

Use this Builder System skill only for bounded read-only discovery or triage of
an explicitly named recipient's Builder Threads. Read
`_shared/BUILDER_THREAD_CONTRACT.md` completely first.

## Boundary

Call the configured `BuilderThreadClient.inbox` or `read` operation through the
designated BuilderOps/Mac mini writer endpoint. The client cannot inspect or
write the external BuilderOps Vault and must not use the repository `vault/`
fixture. Writer unavailability is a typed degraded result; do not infer an
empty inbox or fall back to direct filesystem access.

## Rules

- Reads are bounded and read-only.
- Do not reply, close, archive, create reminders, create backlog, promote, or
  mutate a thread from inbox discovery.
- Do not infer acceptance, delivery, review, approval, or authority from thread
  age, silence, state, or discussion prose.
- Use a separately authorized `builder-thread` operation for a mutation.
