# Builder Thread Contract

This is the shared, non-invocable contract loaded by builder-thread and builder-inbox. The
executable authority for file shapes, validation, bounds, atomic publication, and derived state is
app/builderops/builder_threads.py. The supported operator surface is:

    scripts/builderops_cli.sh builderops builder-thread ...
    scripts/builderops_cli.sh builderops builder-inbox ...

Do not emulate writes with shell redirection or ad hoc Markdown. A client that cannot run the
validated helper remains read-only and must fail closed.

## Purpose And Capture Gate

A Builder Thread is a named-recipient question whose reply must survive a chat/session boundary. It
is not a general notes surface. Create one only when all three conditions hold:

1. a named human, agent, or automation recipient exists;
2. a reply is expected; and
3. the exact subject/source/recipient capture is not already represented.

Monologic working notes, observations, and session narrative remain AgentWorklog. Learning remains
LearningSignal. The helper enforces the capture key and refuses duplicates.

## Vault And Privacy Gate

Every command requires the external BUILDEROPS_VAULT_ROOT and a client-pinned
BUILDEROPS_VAULT_ID. Routine initialization only verifies an existing immutable root/subsystem
genesis pair. First adoption is a separate explicit operator action (`builder-thread init
--adopt-existing`) after the existing BuilderOps vault scaffold validates; it must never be inferred
from a normal create/read/review request. Every later read and write compares the pin to both
genesis envelopes and requires them to match.

The only accepted privacy class is shared_non_sensitive. Content, subjects, source refs, thread
entries, and outputs are bounded. The helper rejects credential-like material, argv/env/stderr
captures, raw private host paths, unsafe or untyped refs, symlinks, SQLite, conflict-copy names,
unknown or incomplete artifacts, duplicate IDs, non-canonical JSON, hash mismatches, wrong vault
identity, and replay conflicts.

Never point this workflow at Mimer, a human knowledge vault, or the repository vault/ fixture.
Never put product code, patches, binaries, secrets, or machine-local state in a Builder Thread.

## Immutable Artifacts And Recovery

Each contribution is one canonical JSON envelope at:

    builder-threads/threads/<thread-id>/entries/<slot>/<sha256>.json

Before publishing that envelope, the writer atomically claims its vault-wide entry UUID with one
immutable visible manifest at `builder-threads/entry-claims/<entry-id>.json`. The manifest binds the
entry ID to exactly one thread and is validated one-to-one with represented contributions. It is a
concurrency guard and recovery artifact, not a mutable index, sequence, backlog, or authority.

Canonical bytes are UTF-8 JSON with object keys sorted lexicographically, no whitespace outside
strings, comma/colon separators, JSON Unicode characters emitted directly, and one terminal LF.
The filename is the SHA-256 of the complete canonical envelope bytes. Writers use a same-directory
temporary file, file fsync, a no-overwrite hard link, directory fsync, readback verification, temp
unlink, and a second directory fsync. Readers reconstruct state from all validated contributions;
there is no mutable sequence, latest pointer, database, distributed lock, or hidden local index.

The initial thread UUID is deterministically derived from the pinned vault ID and capture key. Its
destination directory is claimed with create-if-absent semantics and is never replaced or
overwritten. Readers wait for the bounded live-install window and accept the tree only after its
entries directory, reserved slot, and complete content-addressed entry exist. A pre-existing empty
destination is a typed conflict and remains untouched.

Create/reply require a caller-retained entry UUID. Reusing it for the same semantic request is an
idempotent acknowledgement-loss retry even when the new invocation has a later generated timestamp;
changed content under that ID is a replay conflict. The claim uses create-if-absent publication, so
concurrent cross-thread reuse has one winner before either thread envelope can publish. A claim-only
crash is incomplete to readers and recoverable only by an exact writer retry. A committed temp
hard-link twin left by failed cleanup is removed only by a mutation retry after its bytes and
content-addressed final match. Read-only health exposes unmatched claims and orphaned temps as
incomplete.

Stale close/archive snapshots may be superseded through immutable hash lineage. Each thread has 128
immutable, create-if-absent entry slots. A writer must reserve one before publishing contribution
bytes, so a concurrent or sequential 129th append fails without changing the thread. Concurrent
incompatible quarantine decisions for one target fail closed. Only when at least two active sibling
decisions exist may one decision be quarantined with `concurrent_conflict` to preserve the other
while a slot remains; a lone decision cannot be neutralized this way. Entry IDs are vault-wide
identities: reuse for changed semantics, conflict-copy siblings, partial temp artifacts, and
uncertain lineage fail closed.
An explicit quarantine contribution may disposition a structurally valid unsafe artifact by exact
hash. It preserves the original bytes, redacts them from normal output, and never hides structural
corruption. Incident handling is explicit; no free-form session capture or automatic quarantine is
allowed.

## Authority Boundary

Builder Threads are attributed context only. They never:

- grant a claim, lease, approval, review result, or owner decision;
- satisfy Verify, CI, merge, delivery, parent closure, or acceptance;
- create or mutate an Issue, PR, branch, design handoff, PromotionIntent, receipt, or runtime state;
- authorize inbox review to reply, close, archive, quarantine, remind, or promote.

External effects use the existing owning skill and gate. A thread may cite an already-existing
result, but it cannot create or certify that result.

## Read And Review Idempotence

builder-inbox is read-only. It derives bounded summaries and one deterministic snapshot hash from
validated envelopes. An unchanged artifact set produces the same output and no write. Inbox review
has no reminder entries, review receipts, recursive trigger, or learning-retrospective coupling.
Mutation requires a separately authorized builder-thread command.

## Failure Output

Report the safe failure class, thread or artifact ID, and bounded next action. Never print rejected
content, absolute vault paths, credentials, raw stderr, argv, or environment values. Hash/root/
identity/conflict failures stop the operation rather than returning an empty or healthy result.
When `--json` is requested, operation, configuration, and command-usage refusals return one bounded
typed JSON error envelope rather than Click prose.
