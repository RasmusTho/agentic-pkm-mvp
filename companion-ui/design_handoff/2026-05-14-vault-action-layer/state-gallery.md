# State gallery — Vault Action Layer

The full visual gallery lives in **`prototype.html` §06**. This file mirrors the state
list for code review and acceptance-criteria use.

## States

1. **Allowed move** — Tier 2 success path. All nine steps pass. Receipt minted.
2. **Denied · source** — refused at step 03 because the note type is not `inbox-item`.
3. **Denied · destination** — refused at step 03 because destination is outside any declared
   vault domain.
4. **Blocked · write guard** — steps 03–04 pass; step 05 refuses (focus-mode policy).
5. **Idempotent no-op** — same idempotency key as a prior action within window; step 06
   returns no-op. A receipt is still produced.
6. **Collision · resolved** — destination already exists; step 07 applies the deterministic
   suffix rule. Auditable; not random.
7. **Success with receipt** — canonical success shape; receipt durable, inspectable, undo
   available.
8. **Receipt inspection** — audit view of the same trace with parameter dump, idempotency
   key, adapter, linked outbox event.

Each gallery card shows: the resolved action name, the step at which the verdict was
reached, the relevant evidence captions, and a terminal outcome tag (`APPLIED`, `DENIED`,
`BLOCKED`, `NO-OP`, `RESOLVED`, `INSPECTED`).
