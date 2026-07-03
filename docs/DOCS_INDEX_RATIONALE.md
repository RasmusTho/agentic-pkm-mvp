State: Rationale register extracted from DOCS_INDEX Notes 2026-07-03; advisory, non-normative.
Doc role: Reference

# DOCS_INDEX Rationale Register

Relocated decision-history and rationale prose that was previously carried in the `docs/DOCS_INDEX.md`
Notes column. `DOCS_INDEX.md` Notes cells are now condensed to doc role + key pointers; this file
preserves the longer-form rationale for rows where that context is not otherwise recoverable from the
target doc itself, its `State:` header, an ADR, `docs/STATUS.md`, or the closed governing issues.

Entries are keyed by the `Path` value from `docs/DOCS_INDEX.md`. Non-normative: if this file and the
target doc disagree, the target doc (or its owning ADR/STATUS entry) wins.

## docs/architecture/formal-model.md
Smallest complete formal model of the running system: state tuple Σ=(V,P,S,J,L)+volatile M; full transition catalog with pre/post conditions from three mutation-surface sweeps (T-capture as the reference receipt-before-ack shape); bidirectional invariant mapping to the registry + correctness kernel with five new invariant candidates (guard-at-seam, event-completeness, read-purity, fail-closed guards, receipt-before-ack); nine-seam consistency model (C3/C4/C8 unreconciled — replay from outbox is incomplete); failure domains incl. the object_id rebuild-orphaning coupling; SBS reconciliation (conform; two extend-candidates flagged to CES); adversarially reviewed with corrections recorded in §8. Divergences F-A..F-F → issues #2808-#2810 + owner decisions F-C/F-D on #2778. Consumed by RESEARCH-03 (#2781). Advisory; subordinate to owner contracts.

## docs/architecture/runtime-semantics.md
Per-artifact-class semantics table over 20 persisted classes (vault plane, store rows, event/receipt plane, memory, eval, session) with seven classified divergences (D-1 ephemeral settings receipts, D-2 object-deletion asymmetry, D-3 stale dead-audit-writer claim, D-4 unpersisted session history, D-5 decisions FK cascade, D-6 no GC anywhere, D-7 silent decisions fallback); fix-code/fix-doc follow-ups #2787–#2789; owner decisions surfaced on epic #2778. Baseline for RESEARCH-02 formal model. Advisory; subordinate to owner contracts.

## docs/CONCEPTS/USER_SITUATION_MODEL.md
Dual of the function axis: enumerates the situations/states the human is in when meeting the system (first contact / no vault, boot, warm vs cold return, active session, mid-session interrupt, vault switch, missing vault, multi-vault, device roles, degraded/unavailable runtime, capability-maturity asymmetry) and states grounded human intent per situation. Upstream of the entry-point and vault-optional capability specs, which implement these situations; subordinate to `HUMAN-FLOWS.md` / `USER_NEEDS_MODEL.md`. Settled rows link their governing decision; forward-line rows are marked; an Open Decisions register collects product choices and reconciliations (R1 first-contact flow — DECIDED 2026-06-24, #2488, as a guided create-or-open chooser with no manual path entry, dyslexia-friendly, downstream reconciliation pending; R2 latency-ladder vs leave-point TTL contradiction — resolved via #2489, 2026-06-24). A cross-cutting dyslexia-friendly input constraint (no typed paths/search strings, ever) binds A1 and B2. Created to give situational decisions (e.g. vault selection) an upstream home instead of being re-argued inside specs.
