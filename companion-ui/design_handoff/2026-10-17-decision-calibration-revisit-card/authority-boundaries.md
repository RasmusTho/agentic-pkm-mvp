# Authority boundaries

| Layer | Owns | This package |
|---|---|---|
| **Design guidance** (this package) | Layout, token use, component grammar, copy, focus and announcement behaviour, state visuals | Authored here. Advisory until promoted through Crossing-B. |
| **Existing normalized spec**: `docs/DECISION_CALIBRATION/SURFACE_REVISIT_REVIEW_CARD.md`, issue `#3324` | Card scope, fields, outcomes, routes, which states exist | Consumed, not modified. Where the spec is silent, the conservative default is noted in `open-questions.md`. |
| **Architecture / runtime truth**: CAL-01 append path, WriteGuard, CAL-02 dismissal ledger, `WorkspaceStateResponse` | Persistence, guards, idempotency, dismissal semantics, projection derivation | Not touched. The prototype mocks these responses for illustration only. |
| **Design system**: Yggdrasil v2.2.1, repo sheet binding | Tokens and grammar | Used as-is. No extensions are used in the prototype. Proposals are listed in `open-questions.md`. |

## Explicitly not in this package
- No edit, re-answer, undo, or snooze-duration controls.
- No new routes, fields, enums, or response shapes.
- No client-side authority. The card never decides that something was recorded without a 2xx response, and never decides "none pending" from an error.
- No changes to the canonical design-system project, owner docs, shipped components, or runtime contracts.
