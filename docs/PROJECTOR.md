State: SoT v4.10 Reality-MVP (current, limited).
# PROJECTOR

Projector decides whether an object should be included in a published set after evaluation; it does not write filesystem artifacts in Reality-MVP.

## Purpose (current)
- Read the latest evaluation decision (`kind=evaluate`) for an object.
- Emit a `promote` flag and audit event (`promotion.project.done` or `promotion.project.skip`).
- Record best-effort set membership (in-memory fallback; DB persistence stubbed).

## Triggers
- Invoked by the promotion pipeline and e2e tests after Reviewer/SetEvaluator.

## Scope & limitations
- No filesystem projection of payloads exists today; only audit + membership stub.
- Membership persistence is a placeholder (`_record_membership_db` is a no-op).
- Output is idempotent and side effects are limited to audit entries and the in-memory fallback.

## Future work
- Persist memberships to the Store/DB and expose published sets.
- If/when file projections are needed, define the layout and whitelist separately.
