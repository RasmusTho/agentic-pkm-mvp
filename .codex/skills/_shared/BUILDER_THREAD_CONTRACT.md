# Builder Thread Contract

This is the shared, non-invocable contract for `builder-thread` and
`builder-inbox`. The executable boundary is
`app/builderops/builder_threads_serialized.py`.

## Serialized Writer Boundary

Builder Threads are attributed, bounded questions to a named recipient when a
reply is expected and no durable representation already exists. `AgentWorklog`
remains the home for monologic notes. Every create, reply, close, and archive
command goes through the one designated serialized writer endpoint operated on
the BuilderOps/Mac mini host. Each Codex or Claude endpoint capability is bound
to that client's identity: clients have no artifact-root or direct mutation API.

The external BuilderOps Vault is never the repository `vault/` fixture. The
writer host owns an explicitly initialized, pinned external root and its
deployment; clients cannot configure or discover that root. The writer records
one immutable, writer-sequenced command envelope per request and rebuilds its
bounded state after a host restart. A client request is bounded and attributed
with its caller-retained request ID, endpoint client identity (which must match
the recorded actor), named recipient where applicable, source references, and
the only permitted privacy class, `shared_non_sensitive`.

An exact retry of an accepted request ID returns the original result. Reusing
that ID with changed semantics fails closed. Writer unavailability is a bounded
typed failure, never permission for a client to fall back to direct filesystem
writes. This is intentionally a one-writer contract, not a distributed lock,
slot reservation, iCloud convergence, or filesystem recovery protocol.

## Capture, Privacy, And Read Bounds

Create only when all of these are true:

1. a named recipient exists;
2. a reply is expected; and
3. the subject, source references, and recipient have no existing durable
   Builder Thread.

Content, subjects, reasons, identities, source references, and inbox results
are bounded. Reject secrets, credentials, bearer material, private host paths,
product code, patches, binaries, and untyped provenance. A thread has at most
32 contributions and the writer retains at most 100 contributions total, so
both thread reads and inbox discovery have fixed bounds. `builder-inbox` is
read-only and returns only bounded thread projections; it cannot reply, close,
archive, promote, or create a reminder.

## Authority Boundary

Builder Threads are non-authoritative attributed context. Discussion notes,
inbox state, and devUI projections cannot create, gate, or mutate Issue
authority, PR authority, CI authority, merge authority, approval authority,
promotion authority, or receipt authority. They cannot satisfy acceptance,
`Verify:`, review, dispatch, delivery, or closure.

GitHub, Git, CI, review, merge, approvals, promotion gates, and receipts retain
their existing authority. A thread may link to already-existing authority but
never certifies it. Promotion or another external action requires its existing
owning skill and explicit authority; it is never inferred from a thread.
