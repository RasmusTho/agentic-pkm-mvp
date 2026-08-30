---
title: Orientation signal projection contract
doc_role: Target-state Product/Runtime contract
authority: Orientation signal meaning, producer precedence, and the retrieval/ASK projection seam
status: Contract only; no runtime projection is delivered by this document
---

# Orientation Signal Projection Contract

## Purpose and boundary

This contract defines the bounded, read-only signal that orientation may derive while a human is
returning to work. It makes the signal path explicit without making it artifact truth: no
`orientation_state`, salience, active-work, or equivalent field may be stored in frontmatter,
object rows, vector rows, mirrors, or commitment records.

The signal is distinct from `source_role`, `evidence_role`, `review_state`, `maturity`, authority,
and topology zone. Those fields retain their own meanings. A request-time projection may consume
authoritative inputs from them, but it must never relabel one of them as orientation truth.

This is a target-state contract. It does not claim that the current ASK path implements these
rules, does not authorize a note or commitment write, and does not reopen #5223 or repair #5228.

## Derived model and precedence

For a requested orientation projection, each candidate receives one derived state:
`active`, `waiting`, `supporting`, `background`, or `unknown`. The state exists only for that
projection and its bounded lifetime. A rebuildable cache may carry it only with the projection
inputs, evaluation time, producer identifiers, and degradation reason; it is never a substitute
for the durable producer and is discarded or recomputed when those inputs are unavailable.

When more than one source applies, use this precedence, retaining all contributing provenance:

1. `active` — a direct, current active-context or session binding to an artifact, commitment, or
   scope. This is the only source that can establish `active` by itself.
2. `waiting` — an open commitment artifact whose authoritative `commitment_state` is `waiting`.
   It overrides less-specific supporting or topology context, but never an active direct binding.
3. `supporting` — an explicit relation, such as a commitment `target_ref` or active-context
   reference, that ties the candidate to an active or waiting item.
4. `background` — frontmatter/path/topology context that describes where a candidate belongs but
   does not establish that it is currently attended to.
5. `unknown` — no sufficient source, a stale or malformed producer, contradictory inputs without
   a deterministic resolver, or an unavailable producer needed to support a precise claim.

Recent activity can corroborate an already direct active binding or order candidates within the
same derived state. It cannot promote an ordinary note to `active`, `waiting`, or `supporting` by
itself. Absence of activity is not evidence for `background`.

## Producer matrix

| Producer | Authoritative contribution | Cannot establish | Required provenance and degradation |
|---|---|---|---|
| Active context/session | Direct current binding establishes `active`; explicit references can establish `supporting`. | `waiting` or artifact lifecycle. | Identify the session/context source and observation time. Missing, expired, or ambiguous context yields `unknown`, not an inferred active item. |
| Commitment artifacts | An open `commitment_state: waiting` establishes `waiting`; a current open commitment and its explicit `target_ref` can establish `supporting`. | `active` without a direct active-context binding; a commitment is not identical to its note. | Preserve commitment id, state, target reference, and read time. Missing, malformed, or conflicting artifacts do not become prose-derived commitments. |
| Frontmatter and path source context | Bounded source context can establish `background` and can corroborate an explicit supporting relation. | `active`, `waiting`, or human intent. | Preserve the frontmatter/path value and topology source. A missing or invalid path/context source yields `unknown`; path placement is never a blanket exclusion. |
| Vault topology | Supplies the meaning and provenance of an allowed path/surface context. | Attention, admissibility, or a durable orientation zone. | Preserve topology decision/source and any degradation from unresolved bindings. Topology cannot make a candidate non-citable. |
| Bounded recent activity | Corroborates direct active context and provides same-state ordering. | Any state by itself, including `background`. | Preserve the event source, bounded window, and observed time. Unavailable activity leaves the state unchanged or `unknown`; it never silently falls back to prose heuristics. |
| Generic vault note ingestion | Supplies ordinary note identity, source path, and `source_role: vault_note` for retrieval. | Any orientation state by itself. | Preserve the note identity/path and ingest provenance. Generic notes remain retrieval candidates; lack of an orientation producer is `unknown`, not background. |

The matrix is producer-specific on purpose. Heuristic body text, a generic `source_role`, a review
posture, maturity, or an all-notes-from-this-folder rule are not admissible orientation producers.

## Projection, retrieval, and ASK seam

Orientation is an intent-specific projection over retrieval candidates, not a new evidence class or
an admission predicate. The required order is:

1. Apply normal scope/policy and context-admissibility rules before ranking; denied material stays
   out of the candidate context.
2. Identify whether the request is an explicit return/reorientation intent. An ordinary retrieval
   question is not orientation merely because it mentions a project, a recent note, or a wait.
3. For orientation intent only, derive the signal from the producer matrix, recording provenance
   and any degradation before ordering the orientation frame.
4. Prefer `active`, `waiting`, and their explicit `supporting` material in the primary frame.
   `background` may be deprioritized in that frame only with its topology/frontmatter provenance;
   `unknown` may not be silently filtered as background.
5. Assemble the context bundle/envelope with every included or excluded candidate's identity,
   orientation provenance, state or degradation, and an exclusion reason where applicable.

The projection cannot override admissibility. Conversely, an admitted or citable candidate is not
automatically active, and `background` does not make an otherwise admitted source inadmissible,
uncitable, or unusable for an ordinary ASK answer. A cache is valid only as a rebuildable,
provenance-bearing projection of these inputs; it must not be read as semantic truth after its
inputs or freshness boundary are unavailable.

### Synthesis and attribution invariant

Every source id emitted by ASK synthesis or recall must resolve to an admitted, citable source in
the assembled context, or be explicitly listed as excluded with a non-content reason. Synthesis may
not attribute a source id that was filtered, denied, unknown only by omission, or absent from the
context bundle. Orientation state explains selection; it never upgrades source authority,
evidence role, admissibility, or citation permission.

## Negative intent and admissibility boundaries

- Do not write a durable orientation or salience field anywhere, including frontmatter, object
  payloads, vector rows, commitment artifacts, traces, or receipts.
- Do not infer active work from generic prose, recent access alone, `source_role: vault_note`,
  `review_state`, `maturity`, `evidence_role`, or a path zone.
- Do not apply orientation filtering to an ordinary retrieval question. Ordinary ASK retrieval
  retains all normally admitted candidates for ranking and citation policy.
- Do not treat `background` as irrelevant, denied, suppressed, non-citable, or non-authoritative.
  It is a derived orientation context label only.
- Do not treat `unknown` as a precise background determination. Return the degradation truthfully
  and retain the candidate where normal retrieval/admissibility permits it.
- Do not turn the projection into human intent, commitment lifecycle, or evidence admissibility;
  those remain owned by their respective contracts and producers.

## Related authority

- `docs/FINDING_AND_REORIENTING/DEFINE_ORIENTATION_CAPABILITY_CONTRACT.md`
- `docs/FINDING_AND_REORIENTING/DOCUMENT_SALIENCE_AS_DERIVED.md`
- `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md`
- `docs/FRONTMATTER.md`
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md`
- `docs/architecture/retrieval-contract.md`
