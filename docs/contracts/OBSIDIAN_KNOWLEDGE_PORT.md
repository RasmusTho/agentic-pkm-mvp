State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Core SoT
Authority: Canonical contract for vault-facing knowledge operations and adapter boundaries; runtime/services must route note operations through this boundary or approved helpers built on top of it.
# Obsidian Knowledge Port Contract

## Purpose
Define one domain-facing interface between agents/runtime and knowledge operations so transport details
(Obsidian CLI vs fallback filesystem adapter) are isolated from business logic.

This contract follows:
- `docs/CONCEPTS/LAYERING_MODEL.md`
- `docs/CONCEPTS/PORTABILITY_CONTRACT.md`
- `docs/CONCEPTS/CONFIG_AS_PRODUCT_CONTRACT.md`
- `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md`

## Runtime posture (current decision)
- Production/server posture: Obsidian Desktop + CLI are required.
- Fallback is not implicit. It is explicitly policy-controlled.
- Startup must fail fast when strict mode is enabled and Obsidian dependencies are not healthy.
- The bootstrap script and runtime health gate must agree on strict-vs-nonstrict behavior; a strict startup setting is not a warning-only mode.

## Interface surface (domain-level)
- `read_note(locator)`
- `write_note(locator, content, expected_version=None, writer_identity=None)` — `expected_version` opts a rewritten note into optimistic concurrency over raw on-disk bytes. The absolute helper preserves the caller-authorized lexical vault-relative locator. The filesystem adapter rejects a locator that already resolves through an alias, classifies the resolved target relative to the canonical vault root, and rejects an expected-version request for a non-`REWRITTEN` class before mutation; it never silently discards the token or blind-writes a create-once or append-only target. An already-stale first comparison leaves the canonical note unchanged, publishes the proposed bytes as a sibling Markdown conflict artifact through the shared classifier grammar, and returns `WriteReceipt(outcome="conflict_staged", conflict_artifact=<vault-relative path>, writer_identity=..., written_at=...)`. A trusted hidden hard link retains the exact proposal until final public-artifact verification, and the outer write path repeats identity-and-byte verification after directory revalidation immediately before its receipt fence; a public-name replacement before that fence fails without a receipt and keeps the proposal recoverable. Each exclusive staging open captures its controlled inode identity before payload write, flush, or `fsync`, and keeps either the owner descriptor or a duplicated guard open so Linux cannot recycle that identity while cleanup remains possible, including when guard duplication itself fails. Cleanup never conditionally unlinks a mutable directory name: it atomically moves the current entry without clobbering to a fresh scanner-inert `_conflicts/*.md.conflict` recovery name, verifies identity after the move, and atomically restores a raced replacement to its original name. A restoration collision fails closed while retaining the replacement in recovery. Controlled staging remnants, including partial pre-publication payloads, remain recoverable and scanner-inert instead of being deleted; their bytes are claimed durable only when their own file `fsync` completed successfully. During initial-stale candidate publication, the prior complete rewrite-staging path remains the proposal-preservation authority. The filesystem adapter anchors the canonical vault root, walks every locator parent component with descriptor-relative `O_DIRECTORY|O_NOFOLLOW`, and anchors the target parent plus its non-symlink `_conflicts` child. All stage, target, exchange, artifact, rollback, and cleanup operations are descriptor-relative. The root-to-parent chain and root/parent/conflict identities are revalidated immediately before exchange and before receipt. Before any other fallible recovery, the caller's known proposal bytes and intended mode are copied to an independently file-fsynced scanner-inert snapshot; staging-inode mutation, staging-name replacement, or later original-snapshot failure cannot erase the intended proposal. The exact checked original is then copied through its still-open descriptor to a second file-fsynced snapshot before primary exchange. If exact hard-link retention of the displaced inode is not proven after exchange, the adapter snapshots that still-open original descriptor again immediately before closing it, capturing late saves after the eager snapshot. Immediately after exchange, the displaced entry must match the exact inode opened before the final version check. A mismatch fails with receiptless `KnowledgeWriteConflict`; it does not run a second exchange because neither POSIX nor macOS exposes an inode-conditional exchange and a stat-then-exchange compensation would recursively race another canonical writer. The adapter retains every still-named displaced entry plus independently fsynced, descriptor-bound snapshots of proposal/original bytes under scanner-inert recovery names. The canonical path is explicitly indeterminate on this receiptless failure path; no success or `conflict_staged` receipt is emitted. A matching version performs one atomic path exchange and preserves the existing permission mode. Before the displaced name is moved, retention creates and verifies an exact scanner-inert hard-link guard; if the move encounters a raced replacement, that guard remains the displaced authority while the racer is restored. Displaced snapshots and rollback-proposal checks read through their already-open exact inode descriptors; mutable recovery names provide authority only when their identity matches before and after those reads. When displaced bytes or mode changed at the exchange boundary, rollback atomically installs a separately fsynced snapshot inode at the canonical target and keeps the live displaced inode only under recovery names, so editing recovery cannot mutate canonical state through a hard-link alias. The proposal is independently snapshotted before that rollback exchange. If rollback does not displace the exact unchanged proposal identity, bytes, and mode, the adapter preserves the observed later writer at the scanner-inert rollback name and fails receiptlessly without another exchange; canonical outcome is again indeterminate. Each successful exchange publishes two scanner-inert hard-link names for the exact displaced inode under `_conflicts/*.md.conflict`; the receipt fence requires at least one to remain exact, so one concurrently replaced recovery name cannot erase a late save through a pre-existing descriptor or reintroduce stale note content into search/projection readers. File data and affected directories are `fsync`ed before success. Missing targets and races after the first comparison fail with `KnowledgeWriteConflict`; rollback and rollback-failure preservation use the same descriptor-anchored filesystem tree. Cleanup failures preserve recovery artifacts, close all adapter descriptors, and fail closed where a safe restoration cannot be proven. Unsupported descriptor-relative, atomic no-replace rename, or atomic-exchange platforms fail closed with `KnowledgeCapabilityError`.
- `append_note(locator, content)`
- `prepend_note(locator, content)`
- `search_notes(vault, query, limit=20)`
- `open_note(locator)`

Approved candidate-only helpers, not new `KnowledgePort` methods:

- `candidate_note_exists_durable(note_rel_path, vault_root=...)` walks an existing parent chain
  descriptor-relative without following symlinks or mutating the vault. It returns true only for a
  regular target after target-parent fsync; missing paths return false, and all other probe or close
  failures are loud.
- `create_candidate_note_once(note_rel_path, content, vault_root=..., action=..., write_guard=...)`
  asserts WriteGuard before mutation, durably prepares only the target's local parent chain, writes
  a complete hidden raw-FD stage, and publishes through the existing descriptor-relative atomic
  no-replace primitive. `written` follows target-parent fsync; an `EEXIST` loser cleans only its own
  stage, fences the parent, verifies the regular winner, and returns `already_exists`.

These helpers are restricted to the shipped YouTube candidate writeback. They neither broaden
generic port/adapter semantics nor migrate Heimdal, Karakeep, or other `Sources/` producers. Their
guarantees assume one user on macOS/Linux and one local filesystem; they provide no global lock,
fairness, network-filesystem, or distributed-writer contract.

The `write_note` receipt above is the low-level port result. Production/service callers use
`write_note_from_absolute` or `write_note_relative`; those helpers raise
`KnowledgeWriteConflict` with the staged receipt attached when `outcome="conflict_staged"`.
Consequently, a normal helper return continues to mean the canonical write completed. A caller
that understands the non-canonical result may opt in explicitly to receive the staged receipt and
must branch on `outcome` before acknowledging success or running downstream effects.

Text-producing callers MUST bind decoded UTF-8 content and `expected_version` to the same raw
filesystem read; direct read/transform/write paths use `read_note_text_with_version`, whose version
is SHA-256 over those exact bytes. `read_text()` followed by UTF-8 re-encoding is invalid because
newline normalization can change the token. For a read/transform/write pipeline, acknowledgement
effects are post-write: version-aware panel service/watcher flows prepare without ID persistence or
event dispatch/emission, perform the canonical write, then commit non-empty executed IDs and
eligible effects. An attached `conflict_staged` receipt cannot advance a snapshot or those effects.
A receiptless/other `KnowledgeWriteConflict` is not classified as stale: it propagates as an
indeterminate error because the write may already have linearized. Both direct watcher writeback
paths first resolve the candidate against the canonical vault root, reject symlink aliases, admit
only paths classified `REWRITTEN`, then route through the hardened absolute helper.
`CREATE_ONCE` Sources and append-only paths never enter watcher UUID healing, preparation,
writeback, or acknowledgement. `OptimisticWriteGuard.write_if_unchanged` is a check-then-write
utility, not an approved rewritten-note CAS.

Reference types:
- `NoteLocator(vault, path)` where `path` is vault-relative and portable (`/` separators).
- `WriteReceipt(operation, locator, adapter, trace_id, fallback_used, note_class, writer_identity, written_at, outcome, conflict_artifact)`.
- Locator construction for runtime/services must go through shared helpers:
  - `resolve_obsidian_vault_name(...)`
  - `make_note_locator(...)`
  - `make_note_locator_from_absolute(...)`

## Policy surface
- `KNOWLEDGE_PRIMARY_ADAPTER` (`obsidian_cli` or `fs_vault`)
- `KNOWLEDGE_FALLBACK_ADAPTER` (`obsidian_cli` or `fs_vault`)
- `KNOWLEDGE_ALLOW_FALLBACK` (`0|1`)
- `KNOWLEDGE_STRICT_STARTUP` (`1` by default)

Validation rules:
- Primary and fallback adapters must differ.
- `strict_startup=1` cannot be combined with `allow_fallback=1`.

## Obsidian CLI invariants
- Scope argument must be injected as first argument: `vault=<...>`.
- CLI availability and installer compatibility (`>= 1.12.4`) are dependency checks.
- Dependency checks are treated as startup gates in strict mode.

## Error taxonomy
- `KnowledgeConfigError` (invalid policy/settings)
- `KnowledgeDependencyError` (missing CLI/installer dependency)
- `KnowledgeCapabilityError` (adapter cannot perform requested operation)
- `KnowledgeWriteConflict` (safe write preconditions fail)

## Allowed exceptions (boundary)
- Startup/ops glue may reference Obsidian only for dependency gates and telemetry:
  - `scripts/start_full_system.sh`
  - `app/cli/health.py`
- URI rendering helpers may stay outside adapter classes but must only consume `NoteLocator` (no ad-hoc vault/path parsing).
- No domain/service code may construct `NoteLocator` directly from env vars; use shared locator helpers instead.

## Allowed write operations

The KnowledgePort boundary is the normative write path for:
- normal vault note writes and appends,
- UUID healing writes back into vault notes,
- companion-note creation and update,
- bounded system-surface writes under system-owned paths,
- and repair writes that restore continuity metadata without silently redefining human meaning.

System-owned path clarification:
- `<system_folder>/companions/` (layout-aware; e.g. `⚙️ System/companions/`) is the canonical system-owned vault path for companion-note artifacts. The legacy `_system/companions/` path is a read-only fallback for vaults that have not yet migrated; no new files are written there.
- Runtime/services may write companion notes only through KnowledgePort or approved helpers built on top of it.

KnowledgePort may not:
- bypass write-policy and safety checks through ad-hoc direct filesystem mutations as the normative
  path,
- silently redefine human-authored meaning-bearing body content under the banner of healing,
- or promote runtime/index artifacts into human-surface truth by write side effect alone.

## Required test baseline
1. Contract tests for `NoteLocator` portability constraints.
2. Settings tests for adapter policy parsing + invalid combinations.
3. CLI scope tests enforcing `vault=<...>` first.
4. Dependency health tests for missing CLI and installer version checks.
5. Architecture guardrails preventing direct `NoteLocator(...)` construction and direct `OBSIDIAN_VAULT_NAME` reads outside shared helpers.

Current enforcement:
- CI/architecture tests enforce the boundary in `tests/architecture/test_obsidian_port_boundaries.py`.
- Runtime/service writes are expected to route through `app/knowledge/write_ops.py` or deeper `app/knowledge/*` modules rather than direct service/runtime wiring.

## Rolling implementation backlog
- [x] Verify all runtime call sites that perform note open/search are explicitly routed through `resolve_knowledge_port()`.
- [x] Add contract tests for `make_note_locator_from_absolute(...)` usage in service flows with mixed absolute/relative paths.
- [x] Add CI marker command in runbooks for `tests/architecture/test_obsidian_port_boundaries.py`.
- [x] Route settings auto-heal/writeback note updates through `KnowledgePort` (`app/settings/writeback.py`, `app/settings/compiler.py`).
- [x] Route vault layout/system-note bootstrap writes through `KnowledgePort` (`app/vault/layout.py`).
- [x] Route alpha human flows vault note mutation writes through `KnowledgePort` (`app/cli/alpha_human_flows.py`).
- [x] Route note update + promotion note writes through `KnowledgePort` (`app/services/note_update.py`).
- [x] Route Mimer bootstrap settings placeholder writes through `KnowledgePort` (`app/settings/mimer_scaffolder.py`).
- [x] Route vault ingest mirror-note writes through `KnowledgePort` (`app/ingest/vault_alpha.py`).
- [x] Route note hygiene archive-note writes through `KnowledgePort` (`app/agents/note_hygiene/agent.py`).
- [x] Centralize service/runtime vault write+append wiring behind `app/knowledge/write_ops.py` helper functions (`write_note_from_absolute`, `write_note_relative`, `append_note_relative`).
- [x] Centralize Advanced URI vault-path conversion via `app/knowledge/write_ops.py::advanced_uri_from_vault_path` and remove ad-hoc locator parsing from runtime/services.
