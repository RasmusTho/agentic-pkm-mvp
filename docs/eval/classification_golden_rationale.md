# Classification golden set — case-family rationale

State: Advisory eval ground-truth rationale for `docs/eval/classification_golden.yaml`
(`classification_case.v1`). Authored under issue #2784 (RESEARCH-06); adopted by
KERNEL-13 (#2775), which wires the runner, scorecard slice, thresholds, and CI gate.
Spec: `docs/RUNTIME_CORRECTNESS_KERNEL/INTENT_CLASSIFICATION_GOLDEN_SET.md`.

## Why this dataset is adversarial by design

The intent classifier (`app/chat/intent_classifier.py::classify`) is the LLM decision
that gates mutations. The audit failure mode (CW-2) is *silent conversion*: a
governance-bearing intent read as a body edit, or an exploratory question read as an
action. Cases were therefore authored to probe specific confusion boundaries rather
than to pad accuracy on easy inputs. 46 of 68 cases (~68%) are boundary/adversarial,
above the ≥1/3 floor in #2784.

Cost asymmetry used throughout (mutation-side vs read-side):

- **Mutation-side confusion** (expected exploratory/unknown → action-capable class):
  the system acts, or stages an action, the user never asked for. `co_authoring` is
  the worst case (ungated body write); `governance_bearing` stages a wrong intent in
  the gated pipeline. This direction is the KERNEL-13 **hard gate** (blocking, zero
  tolerance).
- **Read-side confusion** (expected action-capable → exploratory): the ask silently
  drops. Annoying and trust-eroding, but recoverable; thresholded, not blocking.
- **`unknown` is safe-fail**: scored separately, never as a wrong class. It is the
  designed landing for ambiguity (KERNEL-07 re-ask affordance), so it never appears
  in `acceptable` lists.

Dataset invariant protecting the hard gate: every case with
`expected_intent ∈ {exploratory, unknown}` has an `acceptable` list free of
action-capable classes. Otherwise the dataset itself would contradict the gate.

## Family-by-family rationale

### `coauthor-*` — plain co-authoring (8, plain)

- **Boundary probed:** none — anchors. Establishes that unambiguous body-edit requests
  land in `co_authoring` in both languages, so the boundary families measure confusion,
  not baseline incompetence.
- **Wrong-route cost:** read-side (dropped edit) or governance-side (spurious staged
  action); both thresholded.

### `gov-*` — plain governance commands (8, plain)

- **Boundary probed:** none — anchors. Covers every `GovernanceActionType`
  (`maturity_transition`, `frontmatter_update`, `note_lifecycle`, `cross_note`) in
  both languages with imperative phrasing.
- **Wrong-route cost:** mutation-side if read as `co_authoring` — the exact CW-2
  failure (a "promote to evergreen" applied as prose edit). This family failing means
  the classifier is unusable, independent of adversarial performance.

### `explore-*` — plain exploratory (6, plain)

- **Boundary probed:** none — anchors for the read-only class, including recall-style
  questions ("Vad var det jag skrev…") that must not become edits.
- **Wrong-route cost:** mutation-side (hard gate) if routed to any action-capable class.

### `govchat-*` — governance phrased as casual chat (8, boundary)

- **Boundary probed:** governance intent without imperative surface form — musing tone,
  hedges ("kanske dags att…", "…doesn't it"), first-person-plural drift. A keyword or
  syntax heuristic sees chat; the semantics carry a state-change ask. All four action
  types appear in casual form.
- **Wrong-route cost:** `co_authoring` here is mutation-side (silent body edit of a
  governance ask). `exploratory` is read-side; for the three softest musings it is
  listed in `acceptable` because a human reader could also take them as observations —
  the family still forces the *directional* asks to route to the gate.

### `cmdstyle-*` — body edits phrased as governance-sounding commands (6, boundary)

- **Boundary probed:** the mirror image of `govchat`. Imperatives with lifecycle
  vocabulary (`delete`, `rename`, `move`, "ta bort", "döp om", "flytta") whose objects
  are *in-note content* (paragraph, heading, list), not the note. This is the family a
  keyword heuristic misroutes 6/6; an LLM must resolve the object of the verb.
- **Wrong-route cost:** staging a `note_lifecycle`/`cross_note` action the user never
  asked for — a wrong intent presented for approval (governance-side), or a dropped
  edit if read as exploratory. Both erode trust in the gate itself.

### `readvocab-*` — exploratory with mutation vocabulary (8, boundary, hard gate)

- **Boundary probed:** archive/promote/merge/tag appearing inside questions about the
  past ("Which notes did I archive…"), definitions ("What does promoting… change?"),
  hypotheticals ("If I merged…"), and provenance ("why I tagged…"). Protects the
  LLM-over-heuristics decision: any keyword router fails this family wholesale.
- **Wrong-route cost:** pure mutation-side — a recall question becoming an archive
  action is the highest-cost failure in the system. Every case here feeds the
  `P(action-capable | expected exploratory) = 0` hard gate; `acceptable` is empty
  throughout.

### `vague-*` — genuinely unresolvable → `unknown` (6, boundary, hard gate)

- **Boundary probed:** missing antecedents ("the thing we talked about", "samma som
  förra gången", "det där") with an open note as bait. There is no reading that
  resolves to a concrete action, so a confident classification is a *fabricated*
  route. These cases exercise KERNEL-07's explicit `UNKNOWN` + re-ask landing and
  keep the removed `CO_AUTHORING` default from regressing.
- **Wrong-route cost:** mutation-side by definition — any action-capable class is the
  classifier inventing intent; blocking.

### `polite-*` — Swedish politeness/indirection (6, sv, boundary)

- **Boundary probed:** Swedish conditional/hedged request forms — "skulle du kunna…",
  "det vore bra om…", "det hade inte skadat om…", "man borde kanske…" — that carry
  real, resolvable intent (all four governance action types plus two body edits). An
  English-trained pattern reads these as chit-chat; a literal reader demotes them to
  exploratory. Indirection must change neither the class nor the action type.
- **Wrong-route cost:** read-side demotion makes the assistant unusable in idiomatic
  Swedish (asks silently dropped); `co_authoring` on the governance forms is
  mutation-side. This family is why the set is bilingual rather than translated.

### `multi-*` — multi-intent utterances (8, boundary)

- **Boundary probed:** one utterance, two intents; the classifier's contract is ONE
  class or `unknown`. Encoded resolution policy:
  - body-edit + governance ("tighten … and archive") → `governance_bearing` must win:
    the gated pipeline is the safe route, and the riskier component must not silently
    drop into a body edit;
  - opinion + hedged edit ("What do you think? Maybe shorten…") → `co_authoring`,
    with `exploratory` acceptable (both readings are safe);
  - contradictory combinations ("archive it, but keep expanding it") → `unknown`;
    only a re-ask is truthful, and these two cases are hard-gate cases.
- **Wrong-route cost:** picking the weaker component of a governance-bearing pair is
  mutation-side (CW-2); for the contradictory pair, any confident class is fabricated
  intent (blocking).

### `xlang-*` — cross-language idiom (4, boundary)

- **Boundary probed:** code-switching a Swedish user actually produces — Swenglish
  loan verbs ("deleta", "merga", "tagga … som done") and English commands over
  Swedish note names ("promote 'Veckoplanering'"). Lexicon-based routing has no entry
  for these forms; semantics must carry.
- **Wrong-route cost:** read-side demotion (dropped governance ask) or mutation-side
  if the loan verb's object is misread; either way the bilingual user loses exactly
  the commands they phrase most naturally.

## Distribution summary

68 cases; 46 boundary (~68%). Per expected class × language (boundary/plain):

| expected_intent | en | sv | boundary | plain | total |
|---|---|---|---|---|---|
| co_authoring | 8 | 10 | 10 | 8 | 18 |
| governance_bearing | 11 | 17 | 20 | 8 | 28 |
| exploratory | 7 | 7 | 8 | 6 | 14 |
| unknown | 4 | 4 | 8 | 0 | 8 |
| **total** | **30** | **38** | **46** | **22** | **68** |

Governance action-type coverage (within the 28 governance cases):

| action_type | en | sv | total |
|---|---|---|---|
| frontmatter_update | 3 | 5 | 8 |
| maturity_transition | 3 | 3 | 6 |
| note_lifecycle | 4 | 4 | 8 |
| cross_note | 1 | 5 | 6 |

## Maintenance notes for the adopting task (KERNEL-13, #2775)

- Field shape is exactly the spec's `classification_case.v1`; `language` follows the
  `retrieval_eval_case.v1` precedent and gives the scorecard its `by_language` slice.
- `context.note_state` vocabulary: `draft-open | seedling-open | evergreen-open | none`;
  `context.surface` is `canvas` throughout (the classifier's surface).
- When growing the set (KERNEL-15 capture loop), preserve the two dataset invariants:
  no `unknown` in `acceptable`, and no action-capable class in `acceptable` when
  `expected_intent ∈ {exploratory, unknown}` — both are what keep the hard gate
  self-consistent.
