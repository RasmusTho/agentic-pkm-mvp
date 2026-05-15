State: Active contract — defines the three artefact surfaces, UUID healing priority order, and scenario authority matrix for vault notes.
---
type: concept-contract
status: active
---

# Artefact Model and Lifecycles

## The Three Surfaces of a Vault Artefakt

A vault knowledge object exists simultaneously on three surfaces:

| Surface | File | Owner | Authoritative for |
|---|---|---|---|
| **Vault note** | `<vault-relative path>.md` | Human | title, tags, body, review_state, maturity, links |
| **Companion note** | `<system_folder>/companions/<uuid>.md` (layout-aware; e.g. `⚙️ System/companions/<uuid>.md`) | System | uuid identity, content_hash, ingest_state, attachment manifest |
| **Runtime DB** | PostgreSQL / in-memory store | System (ephemeral) | chunks, embeddings, relations-index, classification, decisions |

The runtime DB is derivable — it can always be rebuilt from vault note + companion note. The companion note is portable — it moves with the vault via Git. The vault note is the ground truth for human meaning.

## UUID Authority: Healing Priority Order

When the system must determine the canonical UUID for a note, it follows this priority order:

```
1. UUID in vault note frontmatter          → use directly, highest authority
2. Companion note identity record          → restore UUID from companion
3. Runtime DB identity record              → restore UUID from DB
4. source_ref / path match                 → reuse with logging (rename scenario)
5. Exact content_hash match                → reuse in copy/rename scenario
6. Semantic similarity                     → triage only; requires human review
7. No match                                → generate new UUID
```

Steps 1–3 are automatic. Steps 4–5 are logged and flagged. Step 6 is never automatic — it surfaces as a diagnostic. Step 7 is always safe: new identity, no data loss.

## Healing Scenarios and Authority Matrix

### Scenario A: Normal ingest (no prior companion)

```
vault note exists, uuid in frontmatter, no companion file, no DB record
→ Create companion from vault note metadata
→ Create DB record
→ Log: cold-start
```

### Scenario B: Missing companion, DB exists

```
vault note exists, uuid in frontmatter, no companion file, DB record exists
→ Rebuild companion from DB object + vault note metadata
→ Log: recovery (companion rebuilt)
→ companion.ingest_state = "tracked"
```

### Scenario C: Missing companion, DB absent

```
vault note exists, uuid in frontmatter, no companion, no DB record
→ Create companion from vault note metadata alone
→ Create DB record
→ Log: cold-start (companion + DB created)
```

### Scenario D: Damaged companion (malformed YAML)

```
companion file exists but cannot be parsed or has missing required fields
→ Attempt conservative repair using vault note frontmatter as source of truth
→ Log: repair-scenario with old/new values
→ If uuid-ambiguity: flag for human review; do NOT rewrite silently
→ Preserve original file as .bak if repair changes uuid
```

### Scenario E: UUID conflict (frontmatter ≠ companion)

```
vault note frontmatter.uuid ≠ companion.uuid
→ DO NOT apply a blind dominance rule
→ Log: uuid-conflict with both values
→ Frontmatter UUID wins IF companion does not have demonstrably stronger provenance
  (stronger provenance = companion was written after frontmatter was last touched,
   and DB corroborates companion UUID)
→ Flag for human review if ambiguous
→ Never silently rewrite either file without logging
```

### Scenario F: Path change (note was renamed/moved)

```
companion exists, companion.source_ref ≠ current vault path
→ Update companion.source_ref to current vault path
→ Log: path-change with old/new values
→ UUID is preserved; identity is stable across moves
```

## Metadata Ownership Rules

| Field | Owned by | System may... |
|---|---|---|
| `title` | Vault note (frontmatter) | Cache in companion for repair; never authoritative |
| `review_state` | Vault note (frontmatter) | Read for policy; never write |
| `maturity` | Vault note (frontmatter) | Read for policy; never write |
| `uuid` | Vault note (frontmatter) | Write if missing; never overwrite existing |
| `content_hash` | Companion note | Compute and write |
| `ingest_state` | Companion note | Compute and write |
| `attachments` manifest | Companion note | Observe and write; never repair vault embeds |
| chunks / embeddings | Runtime DB | Freely derived and rebuilt |
| classification | Runtime DB | Freely derived and rebuilt |

## Rebuild: Cold Start from Companions

When runtime DB is empty (cold start), the rebuild procedure is:

```
FOR each companion file in <system_folder>/companions/*.md:
  uuid = companion.uuid
  source_ref = companion.source_ref
  vault_note = read vault note at source_ref
  IF vault_note exists:
    → Index into DB using vault note content + companion metadata
    → Log: cold-rebuild
  ELSE:
    → companion.ingest_state = "soft_deleted"
    → Log: companion-orphan (note missing)
```

This guarantees the DB can always be rebuilt from the filbaserade surfaces (vault notes + companions) without any additional state.

## Implementation

- Companion service: `app/services/companion_note.py`
- Ingest pipeline: `app/ingest/vault_alpha.py`
- Plan: `docs/plans/COMPANION_NOTE_AND_NOTE_CONTEXT.md`
