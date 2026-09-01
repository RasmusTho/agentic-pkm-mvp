# Shared epic linkage — Rebuildable System Continuity

State: Filed live shared validation hub #5258 (`agent:blocked`). The full shared validation-hub contract is
`docs/WHOLE_SYSTEM_DESIGN_PRINCIPLES/PARENT_FEATURE_ISSUE.md`; this file owns the continuity child
ledger and terminal acceptance writeback only.

## Continuity Child Ledger

1. RSC-01 — `RECONCILE_CONTINUITY_AUTHORITY.md` — file after DSP-01 is terminal.
2. RSC-02 — `PROVE_PRODUCT_TOTAL_LOSS.md` — file after RSC-01.
3. RSC-03 — `REBUILD_PRODUCT_PROJECTIONS.md` — file after RSC-02.
4. RSC-04 — `DIAGNOSE_MIRROR_CORRUPTION.md` — file after RSC-02 and RSC-03.
5. RSC-05 — `SPECIFY_MVR_NEW_BOOTSTRAP.md` — file after RSC-01 and reconcile with #2143.
6. RSC-06 — `APPLY_MVR_NEW_BOOTSTRAP.md` — file only when the amended MVR prerequisites are live.
7. RSC-07 — `BOOTSTRAP_BUILDEROPS_FROM_AUTHORITY.md` — file after RSC-01; link #5056 without
   broadening its deployment scope.
8. RSC-08 — `VERIFY_CROSS_SYSTEM_TOTAL_LOSS.md` — file after RSC-04, RSC-06, and RSC-07.

## Verification Path

Each child resolves every inline `Verify:` target against its exact PR head. Product fixtures use
isolated stores; MVR and BuilderOps destructive-loss behavior is exercised only in isolated test
fixtures or explicitly authorized test-channel runs. No production loss simulation is inferred.

## Validation / Acceptance Path

The final child records the exact merged heads, the selected design packet, Product reconstruction
proof, MVR/BuilderOps fresh-epoch readback proof, and owner-doc disposition on the shared epic. The
epic stays blocked until this record and both capability ledgers are read back. Current-state docs
may be promoted only for behavior actually delivered and verified.

## Existing Authority Dependencies

- #5056 — BuilderOps VM rebuildability and live activation.
- #2143 and #3863–#3869 — Multi-Vault Runtime delivery chain.
- #5067 — blocked HKA recovery proposal; not an implementation source for this capability.
- #5162, #4659, #2899, #3553 — distinct integrity and effect-spine work.
