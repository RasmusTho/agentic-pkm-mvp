# Builder Vault Deliberation Contract

This is a shared, non-invocable Builder System contract. It is loaded by
`builder-vault-deliberation` and `builder-vault-review`; it is not a third workflow.

## Authority And Scope

Deliberation entries are attributed, non-authoritative context for asynchronous builder work.
They may preserve questions, replies, corrections, and dispositions, but they never grant a claim,
approval, lease, task contract, review result, merge decision, delivery state, or promotion.

GitHub Issues, Git refs and commits, PR head SHAs, required CI, review state, merge results,
dispatchers, explicit approvals, BuilderOps records, and receipts retain their existing authority.
When deliberation material should cross into one of those surfaces, use its existing owning skill and
the existing `PromotionIntent` boundary. Deliberation never creates a parallel promotion path,
backlog, decision ledger, or authority store.

This contract governs only the dedicated Builder System artifact vault selected by
`BUILDEROPS_VAULT_ROOT`. It is separate from Mimer and other human knowledge vaults. The repository's
`vault/` tree is a fixture and must never receive live deliberation content.

## Root And Confinement Gate

Before every live read or write:

1. Require a non-empty, absolute `BUILDEROPS_VAULT_ROOT`.
2. Run `scripts/builderops_cli.sh builderops vault paths --json`; require its
   `shared_vault_root` to resolve to the same directory as the environment binding. Then run
   `scripts/builderops_cli.sh builderops vault validate "$BUILDEROPS_VAULT_ROOT" --json` from a
   current repository checkout. Capture each exit status directly; a failure stops the operation.
3. Require the existing `builderops vault init` scaffold: real, non-symlink directories
   `.builderops/claims/` and `agent-delivery/{Backlog,Ready,In Progress,Review,Blocked,Done}/`. This
   skill MUST NOT initialize an unrecognized root. A missing/incomplete scaffold is
   `unattested_root`; an operator may run the existing init command only after independently
   confirming the dedicated BuilderOps vault selection.
4. Resolve the target beneath `$BUILDEROPS_VAULT_ROOT/deliberations/` without following a symlinked
   root, ancestor, thread directory, entry, manifest, or projection.
5. Refuse when the selected root is the repository root, the repository `vault/` fixture, any path
   inside the current checkout, a root with a top-level Mimer `_heimdal/` control tree, or a path
   equal to or nested beneath a known human/Mimer vault binding. Configuration plus the BuilderOps
   scaffold is a necessary identity proof; any remaining root ambiguity fails closed rather than
   writing.
6. Refuse a target tree containing an iCloud conflicted-copy artifact, duplicate logical entry ID,
   or a file whose observed bytes change during validation. Preserve and report the conflict; never
   delete, rename, merge, or choose a winner.

Reports name the environment binding and vault-relative path only. They never print the absolute
vault root or another private host path.

## Artifact Layout

```text
deliberations/
  threads/<thread_id>/
    entries/<entry_id>.md
    manifests/<manifest_sha256>.md
  projections/<projection_id>.md
```

- `entries/*.md` are the only deliberation source artifacts. Every entry is immutable.
- `manifests/*.md` are immutable, content-addressed snapshots derived from the validated entry set.
  Older manifests remain valid historical snapshots; no mutable latest pointer exists.
- `projections/*.md` are rebuildable, non-authoritative review/search snapshots derived from entries
  and live external authority reads. They may be regenerated or superseded, never edited as source.
- No SQLite database, sequence file, distributed lock, mutable thread file, hidden client state, or
  cross-device write queue may exist under this tree.

Thread and entry IDs use a collision-resistant UUID or an equivalently strong random identifier.
Time or a device-local counter must not be the sole identity source. Filenames contain only their
validated ID; human titles stay in entry content.

## Entry Contract

Every entry is UTF-8 Markdown with LF line endings, one terminal newline, YAML frontmatter, and a
Markdown body. Required frontmatter:

```yaml
---
schema: builder-vault-deliberation.entry.v1
thread_id: bvd_<uuid>
entry_id: bve_<uuid>
entry_type: open | reply | correction | resolution | archive
created_at: <RFC3339 UTC>
actor_type: human | agent | automation
actor_id: <stable non-secret identity>
client_id: codex | claude-code | <other declared client>
session_ref: <non-secret task/session reference or none>
subject: <one line on open; `none` for every other entry type>
target_entry_id: <entry id or none>
target_artifact_sha256: <whole-file SHA-256 or none>
basis_manifest_sha256: <manifest SHA-256 or none>
source_refs:
  - <authority-safe ID, URL, or repo-relative path>
body_sha256: <SHA-256 of the exact Markdown body bytes>
---
```

The only optional frontmatter field is `related_entry_refs`, a list of same-thread
`<entry_id>@<whole-file-sha256>` values used when one additive event must cite more than its primary
target. Every referenced entry must validate before the new entry is accepted.

Rules:

- `open` starts one thread and has no target or basis. Exactly one valid open entry may exist.
- `reply` names the exact target entry ID and whole-file hash it answers.
- `correction` names the exact entry ID and hash it corrects. It explains the correction in its
  body; it never rewrites or erases the target. Two incomparable corrections of the same target are
  a conflict until a later correction targets one and cites the other through
  `related_entry_refs`, explicitly reconciling both.
- `resolution` cites the manifest hash covering the complete validated entry set considered by the
  disposition. It records rationale and any existing external target refs. It does not mutate an
  Issue, PR, doc, skill, approval, or BuilderOps record.
- `archive` cites both the exact resolution entry and the manifest reviewed before archive. Archive
  is a derived visibility state, not a directory move or deletion.
- For `resolution` and `archive`, the cited basis manifest covers every valid entry preceding that
  disposition. The disposition entry itself is not post-basis activity. A valid `archive` that cites
  the current resolution and manifest is not post-resolution activity; any other later valid entry
  is.
- Unknown fields, unknown entry types, missing required hashes, dangling targets, hash mismatches,
  cycles, self-targets, and cross-thread targets fail closed.

Attribution is mandatory and is never inferred from a filename, device name, or chat prose. Actor
identity may be an agent plus session reference; it must not be a credential, email secret, raw host
path, or environment dump.

## Hash And Manifest Rules

For every entry, verify `body_sha256` against the exact bytes after the closing frontmatter delimiter.

A manifest uses exactly this byte serialization, with LF and one terminal LF, no blank lines, and
the frontmatter keys in the shown order:

```text
---
schema: builder-vault-deliberation.manifest.v1
thread_id: <thread_id>
entry_count: <base-10 integer without leading zeroes>
---
<one RFC 8785 (JCS) JSON record per entry>
```

Records are sorted bytewise by ASCII `entry_id`. Each record has exactly these keys; JCS determines
key order, quoting, escaping, and whitespace:

```json
{"actor_id":"...","body_sha256":"...","created_at":"...","entry_file_sha256":"...","entry_id":"...","entry_type":"...","path":"deliberations/threads/<thread_id>/entries/<entry_id>.md","related_entry_refs":[],"target_artifact_sha256":null,"target_entry_id":null}
```

`null` represents a frontmatter `none`. `related_entry_refs` is deduplicated and sorted bytewise;
every scalar is the exact validated entry value. Non-ASCII text is encoded according to JCS, never a
client-specific YAML/JSON emitter. The manifest filename is the lowercase SHA-256 of the entire
manifest file bytes. A reader recomputes these exact bytes from the current entry set and selects or
creates only the matching content-addressed manifest; filename/content disagreement fails closed.

A stale or missing manifest does not make a projection authoritative and does not authorize guessing.
Rebuild it from validated entries first. A missing or invalid entry prevents a complete manifest and
therefore prevents correction, resolution, archive, or a definitive thread-state claim.

## Immutable Write Protocol

Writes are single-artifact, no-overwrite operations:

1. Build and validate the complete bytes in memory. Scan the content boundary in
   `Content Safety` before touching the vault.
2. Open a fresh mode-`0600` same-directory `.tmp-<artifact-id>-<random>` pathname with exclusive
   create. Write only the temporary file, flush and `fsync` it, close it, then re-read its complete
   bytes and hashes. Temporary files are never source artifacts.
3. Install the already-complete inode at the final unique pathname with a no-overwrite hard
   `link(2)`, then `fsync` the containing directory. Never stream bytes into a final pathname and
   never use replace/rename over an existing final pathname.
4. Read the final pathname back and verify the expected whole-file and body/manifest hashes. Only
   after that verification, unlink the temporary pathname and `fsync` the directory again.
5. On a handled failure before the final link, unlink the temporary pathname and `fsync` the
   directory. On failure or crash after a possible link, do not guess: if final and temp are exact,
   verify final, remove temp, and `fsync`; if final is absent, only the original operation with the
   original expected hashes may retry the link; differing or unprovable bytes are preserved and
   reported as an ambiguous write conflict. Readers ignore temporary files as entries but surface
   them for recovery.
6. An exact retry with the same entry ID and identical bytes is idempotent. The same ID with
   different bytes is a conflict and stops.
7. If installation may have succeeded but acknowledgement was lost, read and verify before retrying.

These operations protect one filesystem view. They do not turn iCloud into a distributed lock. A
cross-device conflict remains possible and must be discovered by full-set validation rather than
resolved automatically.

## Derived Thread State

Readers reduce only validated entries:

- `open`: one valid open entry, no valid current resolution;
- `answered`: at least one valid reply exists, no valid current resolution;
- `resolved`: the latest unconflicted resolution cites a complete manifest and no later valid entry
  changes the considered set;
- `archived`: a valid archive cites the current valid resolution and manifest, and no later valid
  entry exists;
- `needs_review`: non-archive activity exists after the latest resolution, a disposition basis is
  stale, or multiple otherwise valid dispositions disagree;
- `conflicted`: any identity, hash, target, correction, manifest, or iCloud conflict is unresolved;
- `orphaned`: the thread lacks one valid open entry or contains dangling/cross-thread lineage.

Ordering by timestamp is for display only. Causal targets, hashes, and manifest membership decide
validity; wall-clock order never resolves a conflict.

## Content Safety

The live shared vault must not contain:

- secrets, credentials, tokens, private keys, cookies, bearer headers, credential fingerprints that
  enable access, environment dumps, raw stderr, or subscription/session material;
- absolute or private host paths, usernames embedded in paths, machine-local configuration, or
  hidden local-state pointers;
- product source code, patches, diffs, generated binaries, database files, or executable payloads;
- human knowledge-vault content or personal data unrelated to builder operations.

Use source references instead: GitHub URLs/IDs, commit SHAs, PR head SHAs, BuilderOps record or
receipt IDs, and repository-relative `file:line` anchors. If safe redaction would change the meaning
of the entry, do not write it; keep the material in its owning authority surface and add only a safe
reference.

## Promotion Boundary

Deliberation resolves with an explicit disposition before any authority crossing:

- owner choice -> `owner-decision-brief`;
- UI/design material -> `yggdrasil-design-handoff`;
- bounded executable work -> `docs-to-issue`, `feature-breakdown`, `learning-to-issue`, or the
  governing Issue workflow;
- delivery divergence -> `capture-learning`;
- cross-authority proposal -> existing `PromotionIntent` plus its receipt path;
- repo-governed artifact -> normal branch/PR publication and verification;
- obsolete or duplicate material -> resolution/archive entry and, when an existing BuilderOps
  object is dispositioned, its existing receipt path.

A deliberation entry may cite these results after they exist. It never fabricates their status or
treats a proposed target as accepted.

## Discovery And Reporting

Discovery scans validated `entries/*.md` first and may use projections only as acceleration. Match
the current task by explicit source refs, repo-relative paths, Issue/PR/commit IDs, and normalized
subject/tags. Report:

- thread ID and subject;
- derived state and last validated activity;
- matching source refs;
- unanswered question or requested disposition;
- external authority links read live when promotion/delivery status matters;
- conflicts or incomplete lineage without exposing private paths.

No matching thread is a normal result. Deliberation availability is not a delivery, resume, claim,
review, merge, or closure prerequisite unless the governing authority contract explicitly names that
specific thread or its promoted target.
