State: Concept contract companion (temporal validity, staleness, and re-evaluation semantics; artifact-centered, not implementation-first).

# Temporal Validity and Staleness Contract

## Purpose

This document clarifies a gap that `maturity`, `review_state`, and `review cycle` do not fully
cover:
- whether an artifact or claim remains valid over time,
- whether it has become stale, drifted, or out-of-date,
- and when re-evaluation is needed even without a new explicit review transition.

It exists so the repo can describe temporal epistemic change without collapsing it into:
- maturity,
- mutation posture,
- or workflow activity.

This document is subordinate to:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`

It is upstream of:
- future re-evaluation policies,
- future freshness/decay heuristics,
- and any runtime logic that surfaces stale or drifted material.

## Core rule

Temporal validity is distinct from both `maturity` and `review_state`.

- `maturity` says how developed or durable an artifact is in its role.
- `review_state` says what review or mutation posture currently applies.
- temporal validity says whether the artifact's claims, applicability, or external fit may have
  changed over time.

These must not be silently collapsed.

## 1. Temporal validity

Temporal validity is the degree to which an artifact, claim, or representation still fits the world,
context, or intended use over time.

Problem solved:
- some artifacts remain structurally mature but drift in relevance or correctness,
- some reviewed artifacts still become outdated,
- and some artifacts remain meaningful historically even when no longer current.

Temporal validity is therefore not a synonym for:
- truth in the abstract,
- current usefulness in every context,
- or whether the artifact should be mutated automatically.

## 2. Staleness

Staleness is the condition in which an artifact or claim may no longer be safely assumed current
without re-evaluation.

Problem solved:
- the human needs to distinguish between "good artifact, but possibly outdated" and
  "immature artifact still being developed."

Staleness does not automatically mean:
- false,
- low maturity,
- or low historical value.

It means that time has become a relevant reason for caution.

## 3. Drift

Drift is the mismatch that appears when an artifact's content, assumptions, references, or
applicability no longer align well with the surrounding world, tool landscape, commitments, or
knowledge base.

Examples:
- a stable note about a tool that no longer exists,
- an evergreen-looking guide tied to an obsolete workflow,
- a retained source whose historical content is intact but whose recommendations are now outdated.

Drift may be:
- external-world drift,
- tool/protocol drift,
- context drift,
- or epistemic drift.

## 4. Historical validity vs current validity

An artifact may remain historically valid even when it is no longer current.

Problem solved:
- many artifacts should still be preserved and usable as records of what was believed, decided, or
  done at time `T`,
- even when they should not be treated as current guidance.

This means:
- historical value and current validity are different,
- retention should not require currentness,
- and stale artifacts may still be important sources.

## 5. Re-evaluation need

Re-evaluation need is the condition that an artifact now merits renewed inspection, checking, or
reframing because of time, drift, changed context, or changed external reality.

Problem solved:
- the system needs language for "look at this again" that is not identical to mutation permission
  or low maturity.

Re-evaluation need may arise from:
- elapsed time,
- changed context,
- broken references,
- changed dependencies,
- changed commitments,
- or contradiction from newer evidence.

## 6. Stable distinctions

### Temporal validity vs maturity

- `maturity` concerns developmental standing,
- temporal validity concerns time-sensitive fit, correctness, or applicability.

A note may be:
- highly mature and still stale,
- immature and still temporally current,
- or evergreen in standing while needing re-evaluation because the world changed.

### Temporal validity vs review_state

- `review_state` concerns review/mutation posture,
- temporal validity concerns whether age and drift now matter.

A reviewed artifact may still become stale.

### Temporal validity vs retention

- retention says the artifact is worth keeping,
- temporal validity says whether it should still be treated as current for some purpose.

A retained artifact may be stale and still worth preserving.

## 7. What should not happen

The repo should avoid:
- using `maturity` as the main proxy for freshness,
- using `review_state` as the main proxy for temporal validity,
- assuming evergreen means permanently current,
- or treating stale artifacts as automatically disposable.

## 8. Representation posture

This document does not yet require one canonical durable field for staleness or temporal validity.

For now, the correct posture is:
- treat these as first-class semantics,
- allow future representation through signals, policies, or explicit markers,
- and avoid prematurely hardening one flat metadata field as the only model.

Possible future representations may include:
- explicit re-evaluation markers,
- freshness signals,
- dependency-based drift warnings,
- or contextual validity annotations.

Those belong downstream of this contract.

## 9. Minimal consequences for current docs and design

1. `evergreen` should not be read as "permanently current."
2. Review completion should not be read as "time-safe forever."
3. Retrieval and surfacing logic should eventually distinguish high-value historical material from
   currently valid material.
4. Re-evaluation semantics should remain possible without forcing every artifact into a new lifecycle
   state.

## Related documents

- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/HUMAN-FLOWS.md`
