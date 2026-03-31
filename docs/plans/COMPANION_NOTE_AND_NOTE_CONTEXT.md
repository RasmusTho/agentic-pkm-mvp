State: Delivered — Parts 1–8 implemented. Ingest migration, VaultMirror cleanup, NoteContext service, Panel Agent wiring, and active doc sync are all shipped.
# Plan: Companion Note + Note Context

**Status**: Delivered (Parts 1–8 done)
**Source**: Consolidated architecture review (2026-03-27)
**Supersedes**: VaultMirror / `note_log.py` pattern

---

## Problem

Three linked problems to solve:

1. **No portable identity artefact** — VaultMirror (`System/Metadata/VaultMirror`) is structurally wrong: path-based layout, duplicates human-owned fields, not flat by UUID.
2. **Agent context starvation** — Panel Agent receives 800 chars of raw text (`graph.py:240`). No relations, no attachments, no history.
3. **Healing is ad-hoc** — `_find_mirror_uuid_by_fingerprint()` and `_load_mirror_frontmatter()` in `vault_alpha.py` scan a path-based mirror tree instead of following a defined authority matrix.

## Solution

- **Companion note** at `vault/_system/companions/<uuid>.md` — flat, bounded, system-owned identity file.
- **Note Context** — ephemeral, runtime-assembled rich context for agents.

---

## Part 1 — Contract docs (no code)

Write the two missing contract docs that the rest of the plan references.

**Tasks:**
- [ ] `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` — bounded field set, path, ownership rules, healing scenarios, what it must NOT contain (review_state, maturity)
- [ ] `docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md` — healing priority order (7 steps), authority matrix per scenario, UUID-conflict rules

**Exit criteria:** Both docs exist and are self-consistent. No code changes.

---

## Part 2 — Companion Note service (new file, no migration yet)

Create `app/services/companion_note.py` alongside its tests. No callers changed yet.

**API surface:**
```python
companion_path(uuid: str) -> Path          # vault/_system/companions/<uuid>.md
read_companion(vault_root, uuid) -> CompanionNote | None
write_companion(vault_root, companion, *, port) -> None
find_companion_by_content_hash(vault_root, sha256) -> CompanionNote | None
scan_attachments(text: str) -> list[AttachmentRef]   # parses ![[...]] embeds
```

**CompanionNote fields (bounded):**
```python
uuid: str
source_ref: str          # vault-relative path
title: str               # repair cache, not authoritative
content_hash: str        # sha256 of stripped text
ingest_state: str        # tracked | stale | soft_deleted
last_ingested: str       # ISO 8601
created_by_instance: str
attachments: list[AttachmentRef]
```

**NOT included:** `review_state`, `maturity`, `kind`, `origin`, `ingest_fingerprint` (dict).

**Tests must cover:**
- Normal read/write roundtrip
- `find_companion_by_content_hash` — found / not found
- `scan_attachments` — `![[file.png]]`, `![[file.png|caption]]`, `![[file.png#anchor]]`, `[[note]]` (must NOT match)
- Missing file → returns None gracefully

**Exit criteria:** `app/services/companion_note.py` + `tests/services/test_companion_note.py` pass. No existing callers changed.

---

## Part 3 — Healing scenarios (extend companion service)

Add healing logic to `companion_note.py`. Still no migration of vault_alpha.

**Functions to add:**
```python
rebuild_from_db(vault_root, uuid, db_obj, vault_note_fm, *, port) -> CompanionNote
repair_companion(vault_root, uuid, *, port) -> CompanionNote   # conservative, logs old/new
resolve_uuid_conflict(frontmatter_uuid, companion_uuid) -> tuple[str, ConflictLog]
```

**Healing scenarios (all must have tests):**

| Scenario | Input | Expected output |
|---|---|---|
| Normal create | New note, no companion | Write companion, return it |
| Missing companion + DB exists | uuid in frontmatter, no companion file | Rebuild companion from DB + vault note |
| Missing companion + DB absent | uuid in frontmatter, no companion, no DB | Create from vault note metadata |
| Damaged companion | Malformed YAML | Conservative repair + log |
| UUID conflict | frontmatter uuid ≠ companion uuid | Log conflict, frontmatter wins unless companion has stronger provenance |
| Path change | source_ref stale | Update source_ref, log |

**Exit criteria:** All 6 healing scenarios covered by tests. `companion_note.py` is self-contained.

---

## Part 4 — Ingest migration (vault_alpha.py)

Wire `vault_alpha.py` to write companion notes instead of VaultMirror files.

**Changes to `app/ingest/vault_alpha.py`:**
- `_write_mirror()` → `upsert_companion()` (calls `write_companion`)
- `_load_mirror_frontmatter()` → `read_companion()` (flat UUID lookup, no dir-traversal)
- `_find_mirror_uuid_by_fingerprint()` → `find_companion_by_content_hash()` (searches flat `_system/companions/`)
- Cold rebuild: check `_system/companions/` not `System/Metadata/VaultMirror`
- Fingerprint skip: compare `content_hash` (scalar) not `ingest_fingerprint` (dict)

**Changes to `app/ingest/config.py`:**
- Add `_system/companions/**` to default `ignore_glob` (more specific than `_system/**`)

**Changes to `app/cli/alpha_human_flows.py`:**
- `note_log_path()` → `companion_path()`

**Verification tests (extend/adapt existing):**
- All existing ingest tests pass with companion paths
- Cold rebuild: empty DB + companions present → full rebuild
- Cold rebuild: empty DB + no companions → clean start
- Fingerprint skip: identical content → skip; changed content → re-ingest
- Idempotency: double ingest → same result
- Watcher: companion writes do NOT trigger new watcher events (validate ignore_glob)

**Exit criteria:** Zero imports of `note_log` in `vault_alpha.py`. All ingest tests green. Event contracts unchanged.

---

## Part 5 — Delete legacy

Remove the now-unused VaultMirror code.

**Delete:**
- `app/services/note_log.py`
- `tests/services/test_note_log.py`

**Verify:**
- `grep -r "note_log" app/` → zero results
- `grep -r "VaultMirror" app/` → zero results
- `grep -r "System/Metadata/VaultMirror" .` → only archive docs (not active code)

**Exit criteria:** No active code references VaultMirror or note_log.

---

## Part 6 — Note Context service

Create runtime context assembler for agents. No agent changes yet.

**Create `app/services/note_context.py`:**

```python
@dataclass
class ContextBudget:
    max_body_chars: int = 2000
    include_relations: bool = True
    include_attachments: bool = True
    include_history: bool = False

@dataclass
class NoteContext:
    uuid: str
    source_ref: str
    content_hash: str
    ingest_state: str
    attachments: list[AttachmentRef]
    frontmatter: dict
    body: str
    outgoing_links: list[str]
    backlinks: list[str]
    classification: dict | None
    executed_actions: list[str]
    kind_policy: dict
    trust_level: str

def build_note_context(
    uuid: str, vault_root: Path, stores, *, budget: ContextBudget | None = None
) -> NoteContext: ...
```

**Tests must cover:**
- Full assembly from all three surfaces (companion + vault note + runtime)
- Budget truncation: body capped at `max_body_chars`
- Missing companion → raises or returns degraded context (decide in impl)
- Missing DB record → graceful (classification=None, history=[])

**Exit criteria:** Service exists, tested. No agent uses it yet.

---

## Part 7 — Wire Panel Agent to Note Context

Replace the 800-char snippet in Panel Agent with Note Context.

**Change `app/agents/panel_agent/graph.py:240`:**
```python
# Before
f"Note (snippet): {(state.note_content or '')[:800]}"

# After
ctx = build_note_context(state.note_uuid, vault_root, stores, budget=PANEL_BUDGET)
# build prompt from ctx.frontmatter, ctx.body, ctx.backlinks, ctx.attachments
```

**Default Panel budget:**
- `max_body_chars=2000`
- `include_relations=True`
- `include_attachments=True`
- `include_history=False`

**Tests:**
- Panel Agent integration test: agent receives full frontmatter + relation count
- Fallback: if Note Context fails, agent degrades gracefully (does not crash)

**Exit criteria:** Panel Agent uses Note Context. The string `[:800]` is gone from `graph.py`.

---

## Part 8 — Doc sync

Update active docs to match implementation. No VaultMirror references in active paths.

**Update:**
- `docs/ARCHITECTURE.md` — remove "transitional compatibility" caveat about VaultMirror
- `docs/DATA_MODEL.md` — update mirror-references to companion note
- `docs/FRONTMATTER.md` — verify companion path is mentioned as system surface

**Do NOT touch:**
- `docs/archive/` — leave as historical record
- `docs/plans/PROTOCOL_SATELLITE_SYNC.md` — check if VaultMirror ref is load-bearing

**Exit criteria:** Active docs (outside `archive/`) consistent with implementation.

---

## Sequence

```
Part 1 (contract docs) → can start immediately, unblocks Parts 2-8
Part 2 (companion service) → after Part 1
Part 3 (healing) → after Part 2
Part 4 (ingest migration) → after Part 3
Part 5 (delete legacy) → after Part 4 green
Part 6 (note context) → can start after Part 2 (parallel with Parts 3-5)
Part 7 (panel agent) → after Parts 4 + 6
Part 8 (doc sync) → after Part 7
```

Parts 3-5 and Parts 6-7 can be parallelized once Part 2 is done.
