State: **Superseded** by [ADR-0055](./ADR-0055-vault-multiwriter-consistency-model.md) (2026-07-07), which resolves #3114 in full. Retained for history — records the interim posture that carried Epic B's B1 wave. The native-app topology design-of-record referenced below is committed alongside at `docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md`.
Doc role: Decision record (ADR, superseded)
Authority: Historical only. The full multi-writer vault-consistency model is now [ADR-0055](./ADR-0055-vault-multiwriter-consistency-model.md); read this ADR for the B1-wave interim posture it recorded, not as current policy.
Owner: Architecture (Rasmus)
Temporal class: Superseded (was: interim decision, expired 2026-07-07 when ADR-0055 landed).
Source of truth: [ADR-0055](./ADR-0055-vault-multiwriter-consistency-model.md); this document is retained for history only.

# ADR-0053: Interim multi-writer vault-write posture — accept last-write-wins for B1; decide the full model before B2

**Date:** 2026-07-06
**Status:** Superseded by [ADR-0055](./ADR-0055-vault-multiwriter-consistency-model.md) (2026-07-07)

---

## Context

The vault is the canonical, human-authored store. It is written live today by the Mac runtime and by the
human via Obsidian; the general write primitive is a blind in-place overwrite with no stale-check
(`app/knowledge/adapters.py:29-33`), so a runtime rewrite that races an Obsidian edit already resolves as
**silent last-write-wins**, with nothing logged. The `docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` pass
found the multi-writer consistency model **undesigned** (§2): the only compare-and-swap
(`app/components/concurrency.py:118-131`) covers just the panel-watcher family, iCloud conflicted-copy
artifacts are ingested as ordinary notes, there is no writer provenance, and no ADR/contract/invariant/issue
governs concurrent same-note writes.

Epic B / B1 (`bifrost#1`) adds the iPhone shell as a **third** live writer over the same iCloud vault. B1's
own contract forbids inventing the consistency model client-side and requires escalation to the hub if it is
undesigned. It is. This ADR is that escalation's landing point: it records the owner's **interim** ruling so
B1 can proceed with the risk owned in the open rather than implied in an issue comment, and it books the
full decision as a hard gate on B2.

## Decision (owner, locked 2026-07-06)

1. **Interim posture: accept silent last-write-wins.** Concurrent writes to the same vault note currently
   resolve as last-write-wins; this is knowingly accepted for the B1 wave. B1 introduces **no** new
   consistency mechanism.
2. **B1 is unconstrained.** The iPhone shell may read and write **any** vault note from day one — including
   rewriting human prose notes the Mac runtime or Obsidian may touch at the same moment. No interim
   note-class scope limit is imposed (owner, 2026-07-06).
3. **The full model is decided before B2.** A dedicated multi-writer vault-consistency ADR MUST be Accepted
   before B2 (#3024) starts, resolving the seven cover-items scoped by the audit (§2): write-primitive
   semantics, conflict posture, iCloud transport semantics, writer provenance, the Bifrost client write
   mechanism, note-class differentiation, and enforcement (INV-VW1/VW2/VW3). Tracked at **#3114**.
4. **B1 cites this ADR**, not a client-side invention, as its consistency posture.

## Constraints honored

- Markdown stays canonical; no consistency mechanism is built here.
- Single owner decision; the supersede-by-full-ADR path is explicit and gated on B2.
- The risk acceptance is recorded in the open (this ADR), not buried in `bifrost#1`.

## Consequences

- B1 proceeds with full read/write immediately. The risk window — silent last-write-wins across every
  surface, including human prose notes — is **real, bounded to the B1 wave, and owned here**.
- The pre-existing runtime-vs-Obsidian collision is now named and owned; it was not introduced by B1.
- #3114 is a hard gate on B2: B2 does not start until the full ADR lands.

## When to revisit

Superseded by the full multi-writer vault-consistency ADR (#3114) before B2. Revisit **earlier** if a
data-loss incident is observed during the B1 wave — that would move the full decision ahead of B1 completion.

## References

- `docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` §2 (undesigned verdict + evidence), §7 (INV-VW1/VW2/VW3), §9 (owner decision point).
- Decision **#3114** (full multi-writer vault-consistency ADR — gates B2); Epic B **#3020**; B1 **#3023**.
- `docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md` — native-app topology design-of-record, committed alongside (the design B1 is verified against).
- `app/knowledge/adapters.py:29-40`, `app/knowledge/write_ops.py:110-127`, `app/components/concurrency.py:118-131` — the write primitives this posture concerns.
