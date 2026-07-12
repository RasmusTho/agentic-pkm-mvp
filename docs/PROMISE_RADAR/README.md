State: Not ready for product implementation — boundary specification only; no new runtime behavior is claimed.
Doc role: Capability boundary / deferred design record
Authority: Records why person-level Promise Radar is not authorized by current contracts. Subordinate to `docs/HUMAN-FLOWS.md`, context-admission, identity, privacy, and commitment owner docs.
Owner: Product / architecture

# Promise Radar

## Human promise

“Show me commitments that are explicitly evidenced as relating to this person, within the life context where they belong — without creating a hidden dossier.”

## Decision

Promise Radar is **not ready for a product issue**. Current commitments do not carry a canonical person relation, source evidence span, consent posture, scope/sphere binding, or person-level query authority. Entity confirmation and capture consent are not authorization to construct relationship memory.

The feature must not be approximated by matching `waiting_on`, `target_ref`, names, aliases, embeddings, recency, or inferred relationship importance.

## Permitted developer probe

A disposable developer-only UX probe may be designed later only if all input is synthetic fixtures. It requires an explicit selection of one resolved canonical entity ID and one declared fixture scope, filters by a pre-authored exact entity link and exact scope equality, persists nothing, performs no network/model call, and is unavailable for live vaults and production builds.

That probe is not a product implementation, evidence of product value, or a path to infer person relationships from existing vault content.

## Product prerequisites

Before a product feature can be scoped, all of the following need an owner-approved contract and implementation evidence:

1. A canonical commitment-to-entity relation with stable identity, creation authority, correction/removal, and migration behavior.
2. Source evidence spans and provenance that explain each attribution.
3. Explicit scope/sphere metadata with fail-closed admission at query and presentation boundaries.
4. Person-level consent/authority distinct from capture consent and identity confirmation, including revocation and retention.
5. Human-governed handling for ambiguous, provisional, merged, split, and disputed identities.
6. Privacy-safe audit/logging, caching, export, egress, and deletion posture that does not become a dossier.

## Non-negotiable safety rules

- No free-text or alias-based person inference.
- No cross-sphere aggregation or fallback.
- No automatic commitment creation, closure, reminder, outreach, ranking, or profiling.
- No display of an ambiguous, unresolved, provisional, or unauthorized identity.
- No persistence of viewed-person history or implicit relationship association.

## Backlog posture

No product implementation issue is created now. The prerequisites are not an invitation to fabricate a general person-memory platform; when adjacent work supplies a specific typed relation and authority path, re-run a Model Inquiry and scope one bounded feature from that evidence.

## Related docs

- `docs/HUMAN-FLOWS.md`
- `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md`
- `docs/COMMITMENT_AS_FIRST_CLASS/README.md`
- `docs/PRIVACY.md`
- `docs/HEIMDAL/CAPABILITY_CHARTER.md`
