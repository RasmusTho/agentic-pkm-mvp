State: Accepted (owner decision, 2026-07-07). Decides the full multi-writer vault-consistency model deferred by ADR-0053, resolving the seven cover-items scoped by `docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` §2. Supersedes ADR-0053. Gates B2 (#3024) per Epic B #3020.
Doc role: Decision record (ADR)
Authority: Authoritative for how concurrent vault-note writes (Mac runtime, human via Obsidian, iCloud sync, Bifrost clients) are detected and resolved. It does NOT implement the mechanism — enactment is downstream work per T2/T3 (`docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` §10). It does NOT design or schedule the future AI-mediated-merge evolution named in §6 below — that is explicitly out of scope for this decision.
Owner: Architecture (Rasmus)
Temporal class: Durable decision (supersede via a new ADR only if the model below is reversed or replaced by the future evolution in §6).
Source of truth: This ADR plus `docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` §2/§7/§9/§11, `docs/adr/ADR-0053-interim-vault-multiwriter-posture.md` (superseded), Epic B #3020 / B1 #3023 / B2 #3024 / decision #3114.

# ADR-0055: Multi-writer vault-consistency model — stale-detection + conflict-copy for rewritten notes, per-note-class posture

**Date:** 2026-07-07
**Status:** Accepted (owner decision, 2026-07-07)

---

## Context

[ADR-0053](./ADR-0053-interim-vault-multiwriter-posture.md) accepted silent last-write-wins as an **interim** posture so Epic B's B1 wave (`bifrost#1`) could proceed, and booked a full decision — tracked at **#3114** — as a hard gate before B2 (#3024). `docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` §2 found the model **undesigned**: the general write primitive is a blind in-place overwrite (`app/knowledge/adapters.py:29-40`), the only compare-and-swap (`app/components/concurrency.py:118-131`) covers just the panel-watcher family, iCloud conflicted-copy artifacts are ingested as ordinary notes (`app/vault/manager.py:241`), and no ADR/contract/invariant governs concurrent same-note writes. The audit scoped seven cover-items (§2) without choosing among them, per its charter.

This ADR is that choice. It was made against a survey of how comparable local-first, cloud-synced, plain-file systems solve the same problem (Dropbox, iCloud Drive, Syncthing, Obsidian Sync, CouchDB/Riak, Git/Wikipedia-style manual merge, and CRDT-based realtime collaboration in Google Docs/Notion/Figma). The chosen model matches the industry-standard tier for "flat files in a synced folder" (tier 1–2 above) rather than the CRDT tier (tier 4), which would require replacing plain markdown with a structured collaborative document format — judged disproportionate for this vault.

## Decision (owner, 2026-07-07)

### 1. Write-primitive semantics
Atomic writes everywhere (temp-file + `os.replace`). Stale-detection (generalize `OptimisticWriteGuard`'s sha256 CAS beyond the panel-watcher family) is added **for rewritten note classes only** (see item 6). Append-only classes keep atomic-append without a stale check. The `append_note_relative` WriteGuard gap (INV-VW2) closes as part of enactment, independent of this posture choice.

### 2. Conflict posture
For rewritten note classes: **detect-and-stage**, not detect-and-refuse. A losing write is never silently dropped and never hard-fails the writer; it is saved alongside the original as a conflict artifact (naming/placement to mirror the existing iCloud `(conflicted copy)` convention the vault already tolerates) for later human or agent resolution. For append-only classes: last-write-wins remains accepted (concurrent appends rarely collide destructively). This states its relationship to `docs/contracts/REPLICATION_ENVELOPE.md`: this ADR's conflict artifact is a **precursor, not an adoption**, of that contract's target-state "conflict envelope" vocabulary — REPLICATION_ENVELOPE remains the strategic federation-scoped contract; this is today's local-file mechanism.

### 3. iCloud transport semantics
Conflicted-copy artifacts (`* (conflicted copy).md` and similar) are detected by the watcher/ingest scan and quarantined — never ingested as ordinary notes. Surfaced to the human for resolution (folder listing / future companion-note affordance), not silently merged.

### 4. Writer provenance / echo
Every writer (Mac runtime, Bifrost clients) tags its own writes with a writer identity and timestamp, carried as a small metadata field alongside the existing write receipt. This is the minimum needed to make conflict artifacts (item 2) legible ("your phone changed this at 14:02 while the Mac wrote it at 14:01") and to give the future evolution in §6 something to reason over. Content-hash idempotence (today's self-write-skip mechanism) is retained as a cheap no-op short-circuit, not replaced.

### 5. Bifrost client write mechanism
Bifrost writes vault files using Apple's coordinated-access APIs (`NSFileCoordinator`/`UIDocument`), not plain `FileManager` I/O. This cooperates with iCloud's own coordination rather than racing it, and keeps the client capable of offline-first operation (no requirement to route writes through the hub API).

### 6. Note-class differentiation
Two classes, not a uniform rule:
- **Rewritten classes** (`_heimdal/**` control/settings/interests/consent/attention/entity notes, human prose notes, companion notes): full stale-detection + detect-and-stage conflict handling (items 1–2).
- **Append-only classes** (capture/inbox appends, event logs): atomic append, last-write-wins accepted, no stale check — the destructive-collision risk this class carries is materially lower.

Enactment (T2, downstream of this ADR) must produce the concrete classification table mapping existing note paths/patterns to one of these two classes.

### 7. Enforcement
**GATE** — checked at every write seam via the existing `WriteGuard` assertion pattern (`app/knowledge/write_ops.py:71,111`), generalized to also cover `append_note_relative` (closes INV-VW2) and the new stale-check path for rewritten classes. Not MUST (no new CI-blocking test suite is commissioned by this ADR) and not DOCTOR-only (a periodic/manual check was rejected — it is exactly how the `append_note_relative` gap went unnoticed).

## Consequences

- B2 (#3024) may proceed once T2/T3 enactment (schema/contract materialization, `append_note_relative` fix, stale-check generalization) lands; this ADR is the ruling, not the implementation.
- The pre-existing two-writer (Mac runtime vs. Obsidian human) silent-collision risk is resolved by the same model, not just the new Bifrost-client case — it was never scoped to B1 alone.
- Human prose and `_heimdal/**` control notes gain real collision protection; append-only surfaces keep today's cheap behavior, proportionate to their lower risk.
- ADR-0053's accepted interim risk window closes; it is formally superseded below.

## §6 Explicitly out of scope: future AI-mediated merge evolution

The owner has expressed a future direction: a git-merge-style flow where an AI agent resolves most conflicts automatically and escalates to the human only when needed, rather than always staging a conflict artifact for manual resolution. This is **not urgent and not judged a significant current problem** — it is recorded here so it is not lost, not designed or scheduled by this ADR.

This ADR's model is compatible with that future direction rather than blocking it: the conflict-staging artifact (item 2) and writer-provenance metadata (item 4) are exactly the inputs an agent-mediated resolver would need to consume. When this is prioritized, it is a new ADR-class decision (agent authority to write the vault unsupervised, escalation criteria, audit/receipt trail) — not an amendment made in passing here.

## Supersession

This ADR supersedes [ADR-0053](./ADR-0053-interim-vault-multiwriter-posture.md) in full. ADR-0053's header is updated to point here.

## References

- `docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` §2 (undesigned verdict + seven cover-items), §7 (INV-VW1/VW2/VW3), §9 (options), §11 (owner rulings).
- [ADR-0053](./ADR-0053-interim-vault-multiwriter-posture.md) — superseded interim posture.
- Decision **#3114** (this ADR resolves it); Epic B **#3020**; B1 **#3023**; B2 **#3024**.
- `app/knowledge/adapters.py:29-40`, `app/knowledge/write_ops.py:71,110-127`, `app/components/concurrency.py:118-131`, `app/vault/manager.py:241` — the write/scan primitives this decision concerns.
- `docs/contracts/REPLICATION_ENVELOPE.md` — strategic federation conflict vocabulary; this ADR's conflict artifact is a precursor, not an adoption.
- `docs/testing/invariant-tests.md` — INV-VW1/VW2/VW3 rows added/updated per this decision.
