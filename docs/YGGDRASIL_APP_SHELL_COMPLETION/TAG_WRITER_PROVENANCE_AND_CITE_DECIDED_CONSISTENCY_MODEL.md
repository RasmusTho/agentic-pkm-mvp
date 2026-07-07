---
name: Tag Writer Provenance And Cite Decided Consistency Model
description: Bifrost client tags its vault writes with writer identity + timestamp (contract §5, ADR-0055 item 4) and its docs cite ADR-0055 + the Mimer client contract as the consistency posture.
task_id: YGGSHELL-02
source_anchor: docs/contracts/MIMER_CLIENT_CONTRACT.md :: §5 Provenance on direct writes
parent_capability: Yggdrasil App Shell Completion
prerequisites: [YGGSHELL-01]
depends_on: [ALIGN_VAULT_WRITES_TO_COORDINATED_FILE_ACCESS.md]
can_parallelize_with: [FIX_FIRST_DELIVERY_REVIEW_FOLLOWUPS]
---

# Tag Writer Provenance And Cite Decided Consistency Model

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec).

## Purpose

Two contract obligations landed after B1 shipped. ADR-0055 item 4 decides that every writer tags its
writes with writer identity + timestamp so conflicts become legible ("your phone changed this at
14:02 while the Mac wrote it at 14:01"). And `MIMER_CLIENT_CONTRACT.md` §8 (Bifrost family) requires
that "B1 cites ADR-0055, not a client-side invention, as its consistency posture" — the shipped
`Yggdrasil/README.md` predates both and presents its own replicated-backend-discipline stance as the
model.

## What This Task Does

- **Provenance on writes.** Every vault note the client *creates* carries the contract §5
  `agent_provenance` frontmatter block (`author: bifrost-ios`, `written_at: <utc-iso>`,
  `origin: direct-fs`; `model`/`trace` omitted where not applicable). Substantive edits to existing
  notes update/append the block. For typed `_heimdal/**` notes this rides the existing
  read-merge-write wrappers (which already round-trip unknown fields untouched); for the generic
  note editor it applies on save. Tagging is best-effort: a provenance failure never blocks the
  user's write (spec invariant INV-B1C-2).
- **Docs cite the decided model.** Rewrite `Yggdrasil/README.md :: Vault write consistency` to
  anchor on hub authority: ADR-0055 (the decided model; item 5 = this client's coordinated-access
  mechanism, landed by YGGSHELL-01) and `docs/contracts/MIMER_CLIENT_CONTRACT.md` §6 (the client
  write discipline W1–W8, recommended for Bifrost until enactment, binding after). Remove the "no
  new multi-writer design was required / this client adds no coordination" narrative — it described
  the ADR-0053 era truthfully but is now stale.

## Concretely

```yaml
# Frontmatter a bifrost-created note carries after this task:
agent_provenance:
  author: bifrost-ios
  written_at: 2026-07-08T09:14:02Z
  origin: direct-fs
```

`grep -n "ADR-0055" Yggdrasil/README.md` finds the citation; `grep -n "no new multi-writer design"`
finds nothing.

## Why This Matters

Without writer identity, a conflict artifact staged by the future hub enactment (#3132) cannot say
*who* wrote the losing version — the whole legibility premise of ADR-0055 item 4 collapses at the
one writer that runs in a pocket. And a shipped client whose own README contradicts the accepted
consistency ADR is exactly the drift the contract's Bifrost-family field exists to prevent.

## Acceptance Criteria

- [ ] Notes created by the client carry the contract §5 `agent_provenance` block with
  `author: bifrost-ios`, `written_at`, `origin: direct-fs`. `Verify:` bifrost
  `Packages/YggdrasilCore/Tests/YggdrasilCoreTests/FrontmatterDocumentTests.swift::testAgentProvenanceBlockOnCreatedNote`
  (new; asserts block shape and round-trip through the YAML codec).
- [ ] Substantive edits through the typed `_heimdal/**` wrappers and the generic editor refresh the
  provenance block without disturbing any other frontmatter field. `Verify:` bifrost
  `Packages/YggdrasilCore/Tests/YggdrasilCoreTests/HeimdalNotesTests.swift::testEditPreservesForeignFieldsAndUpdatesProvenance`
  (new).
- [ ] A provenance-tagging failure degrades to an untagged write plus a client log line — it never
  fails the write. `Verify:` bifrost unit test
  `Yggdrasil/YggdrasilTests/VaultFileStoreTests.swift::testProvenanceFailureDoesNotBlockWrite` (new).
- [ ] `Yggdrasil/README.md :: Vault write consistency` cites ADR-0055 and
  `docs/contracts/MIMER_CLIENT_CONTRACT.md` §6 as the posture and no longer claims no coordination /
  no hub model. `Verify:` doc writeback at bifrost `Yggdrasil/README.md :: Vault write consistency`
  (section names both hub artifacts; stale narrative removed).

## How to Verify (Pre-Merge)

- bifrost CI green (`xcodebuild build test` including the three named tests; `swiftlint --strict`).
- Reviewer greps the README for `ADR-0055` and `MIMER_CLIENT_CONTRACT` (present) and for the old
  "no new multi-writer design" phrasing (absent).

## Out of Scope

- Runtime-side reading/enforcement of the provenance block (hub F1/F2 follow-on, contract §9).
- Per-device identity/keys (contract §9 F2 — the named first hardening slice, owner-ruled not a B1
  blocker).
- The coordination mechanism itself (YGGSHELL-01).

## Related Docs

- `docs/contracts/MIMER_CLIENT_CONTRACT.md` §5, §6, §8 (Bifrost family)
- `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` (item 4)
- `docs/adr/ADR-0056-mimer-client-contract-and-transports.md`
- bifrost: `Packages/YggdrasilCore/Sources/YggdrasilCore/HeimdalNotes.swift`,
  `FrontmatterDocument.swift`, `Yggdrasil/README.md`

## Related GitHub Issues

One implementation issue in `RasmusTho/bifrost` (`type:task`, `agent:ready` once YGGSHELL-01 is
claimed or merged — the two serialize on `Yggdrasil/README.md` and the write path; see spec
INV-B1C-5), linking hub #3023. TCD hint: Sonnet / medium effort — mechanical frontmatter plumbing on
an existing round-trip codec plus a docs rewrite; low hidden-defect risk.
