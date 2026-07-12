State: Specification directory — proposed experiment; no new runtime behavior is claimed.
Doc role: Feature specification
Authority: Defines a narrow read-only temporal-posture experiment. Subordinate to `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md` for semantic boundaries.
Owner: Product / cognitive support

# Temporal Posture

## Purpose

Temporal Posture is a read-only overlay for a deliberately small allowlist of external-source or projection artifacts. It helps the human notice material worth a fresh look without calling historical knowledge false, hiding it, changing its ranking, or modifying it.

## Current foundation and boundary

View/cache freshness and source-vs-index drift already exist, but they are not fact validity. This experiment derives only `unknown`, `historical`, or `review_due` from explicit artifact/source timestamps and a versioned human-readable policy. It does not create a durable claim-validity system.

## First delivery

| Task | Purpose | Status |
| --- | --- | --- |
| [DERIVE_READ_ONLY_TEMPORAL_POSTURE.md](DERIVE_READ_ONLY_TEMPORAL_POSTURE.md) | Implement and evaluate a narrow, policy-driven overlay with no content or retrieval mutation. | First executable slice |

## Interaction safety

- `unknown` means insufficient qualifying date evidence, never low quality or likely false.
- `historical` is policy-designated and preserves original context; age alone cannot create it.
- `review_due` is a review prompt, not a truth judgment. It cannot hide, reorder, expire, or rewrite material.
- Source/index drift and time-based review posture remain two separately rendered signals.
- Policy invalidity, malformed dates, timezone ambiguity, future dates, and mixed-authority kinds fail closed to `unknown` or no overlay; filesystem, ingestion, cache, and embedding timestamps are never invented as evidence.

## Capability acceptance path

After a real allowlisted-corpus run, record whether the wording and policy produce useful, non-misleading results. Only then decide whether a later durable revalidation-result model deserves specification.

## Relationship to GitHub issues

One bounded implementation issue will be created after this specification is merged. No parent feature is needed until experiment evidence justifies a broader capability.

## Related docs

- `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md`
- `docs/RETRIEVAL.md`
- `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md`
