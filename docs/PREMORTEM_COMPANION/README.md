State: Specification directory — proposed capability; no new runtime behavior is claimed.
Doc role: Feature specification
Authority: Defines a future, read-only personal-decision reflection capability. Subordinate to `docs/DECISION_CALIBRATION/README.md` for outcome-receipt truth and to context-admission contracts for retrieval authority.
Owner: Product / decision support

# Pre-mortem Companion

## Purpose

Pre-mortem Companion lets a human pressure-test one explicitly selected decision against admissible outcomes from their own history. It offers cited precedents and clearly labeled questions, not option rankings, predictions, diagnosis, or autonomous advice.

## Current foundation and boundary

Decision Calibration CAL-01 establishes canonical `decision_record` identity (`objects.id` plus `objects.uuid`) and outcome-receipt linkage. The first delivery must reuse those identities and links rather than introduce another resolver; it verifies how an explicitly selected decision reaches that seam and establishes the exact scoped retrieval/admission boundary needed for personal-history reasoning before any model packet is exposed.

## First delivery

| Task | Purpose | Status |
| --- | --- | --- |
| [VERIFY_DECISION_HISTORY_ADMISSION.md](VERIFY_DECISION_HISTORY_ADMISSION.md) | Establish fail-closed decision selection, outcome linkage, scoped admission, and citation behavior. | First executable slice |

Only after that task is accepted may a follow-up render a transient packet with separate evidence, recorded outcome, and model-hypothesis regions.

## Cross-task invariants / interaction safety

- Invocation requires exactly one canonical human `decision_record`; ambiguous or guessed targets fail closed.
- Governance decision logs never enter the personal-decision corpus.
- Every historical claim and outcome shown to the human has a current-scope resolvable citation; unauthorized material is excluded before rendering.
- Sparse, missing, or `unknown_yet` history is a valid result and must not be converted into a personal trait, prediction, or recommendation.
- The first packet is transient and read-only: no vault change, outcome inference, scheduling, profile, action proposal, or follow-up occurs.

## Capability acceptance path

The capability needs a later packet-surface task and adversarial evaluation before it can be supported. The first task's evidence determines whether that surface becomes issue-ready or is redesigned.

## Relationship to GitHub issues

The parent feature and first child issue will be filed after this specification is merged. The parent remains a validation hub while later packet work is gated.

## Related docs

- `docs/DECISION_CALIBRATION/README.md`
- `docs/DECISION_RECEIPT_LOG/README.md`
- `docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md :: decision_record`
- `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md`
