# Open questions — Vault Action Layer

The canonical list lives in **`prototype.html` §10**. This file is the structured version
intended for issue creation at crossings C/D.

## Open questions (summary)

1. **Tier 1 vs Tier 3 distinction.** Both produce queued artifacts for human review. Owner-doc
   should decide whether the split is durable.
2. **Idempotency window.** 24h is a placeholder; per-action default or single fixed value.
3. **Collision rule taxonomy.** `suffix` is the first rule. Future rules (`merge`,
   `refuse`, `timestamp`) should be declared per registry entry, never inferred.
4. **Cross-vault actions.** First action is single-vault. Suggest multi-vault always Tier 3.
5. **Registry-write authority.** Are registry changes themselves governance-bearing? Suggest yes.
6. **Classifier-confidence-to-tier coupling.** None proposed; render for transparency,
   never gate on it.
7. **Receipt retention.** Suggest: forever, in vault, as a subordinate artifact.

## Crossing-B blocker triage

The reviewer at crossing B must classify each question as:

- **resolve before promotion** — likely #1, #4 (would change the tier matrix).
- **resolve in normalized spec** — likely #2, #3, #5, #7.
- **defer to implementation issue** — likely #6.
