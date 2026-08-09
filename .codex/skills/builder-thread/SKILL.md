---
name: builder-thread
description: "Create, read, reply to, close, or archive one attributed Builder Thread through the designated serialized BuilderOps writer."
---

# Builder Thread

Use this Builder System skill for a durable question to a named recipient only
when a reply is expected and it has no existing durable representation. Read
`_shared/BUILDER_THREAD_CONTRACT.md` completely before an operation.

## Boundary

Use the configured `BuilderThreadClient` for the designated BuilderOps/Mac mini
writer endpoint. Do not point it at the repository `vault/` fixture, pass a
vault path, write an artifact tree, or run a client-side fallback when the
writer is unavailable. The live external BuilderOps Vault is operated outside
this repository.

## Allowed Operations

- `create`: require caller-retained request ID, endpoint-bound actor identity,
  named recipient, bounded subject/content, and typed source references.
- `read`: read one bounded thread projection through the endpoint.
- `reply`: require a caller-retained request ID, endpoint-bound actor identity
  and named recipient, bounded content, and source references.
- `close` and `archive`: require explicit task/user authorization; close only
  answered threads and archive only closed threads.

Use `shared_non_sensitive` content only. An exact retry may return the existing
result; a changed request under the same request ID is a terminal conflict.
Route monologic work notes to `AgentWorklog` instead.

## Authority

This workflow captures attributed context only. It never establishes or changes
Issue, PR, CI, merge, approval, promotion, or receipt authority. Re-read the
owning authority live and invoke its existing skill for any external action.
