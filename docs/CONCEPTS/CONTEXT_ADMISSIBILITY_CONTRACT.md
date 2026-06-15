State: Concept contract companion defining the inbound context/memory admissibility predicate (admit-by rule) — the input-side analogue of the outbound `AuthorityFlags`. Normative for new work; runtime enforcement is delivered separately (parent #2022, Slice #2025).
Doc role: Concept contract companion
Authority: Canonical owner of the **inbound** admit-by predicate — what context and memory is *eligible to enter* a proposal, answer, or action. It does **not** redefine the **outbound** authority axis (what a selected item *may do*); that remains owned by `app/context_bundles/schema.py` (`AuthorityFlags`) and `app/agent_memory/authority_guard.py`. This contract supersedes the documented-only conservative default recorded under #1598 in `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` and `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`.

# Context Admissibility Contract (inbound admit-by predicate)

## Purpose

Every existing admissibility primitive in this repo governs the **outbound** axis — what a *selected*
item is allowed to *do*:

- `AuthorityFlags` (`app/context_bundles/schema.py`): `may_answer` / `may_orient` / `may_resurface` /
  `may_propose` / `may_write` on an assembled bundle.
- `app/agent_memory/authority_guard.py`: whether a *recalled* memory may escalate to mutation
  authority.

Neither answers the prior, **inbound** question: *what context or memory is even eligible to enter a
proposal, answer, or action in the first place?* `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
and `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` document a conservative three-tier *influence* default
(the #1598 default), but that default describes how already-admitted material may influence each tier;
it does not define the admit-by predicate, and nothing enforces it.

This contract defines that predicate. It is the **input-side analogue of `AuthorityFlags`**: a
deterministic, inspectable rule that, given a candidate item and a declared consuming authority,
returns **admit** or **exclude-with-reason** for each of four admission axes, then composes them.

This is reset critical-path step 5 (`docs/plans/MAJOR_ROADMAP_RESET_2026_06_04.md`, Wave 5):
"Define memory/context admissibility before memory can influence proposals or action." The activation
gate (#2024) consumes this predicate as a gate input; the deterministic gate function (#2025)
implements it. This is a docs-authoring contract — **no runtime enforcement is defined here**.

## Scope of the predicate

The predicate decides admissibility **into a declared consuming use** at one of three influence tiers,
reusing the tiers already named by the #1598 default:

- **read** — read-side awareness, orientation, resurfacing, answering (`may_answer` / `may_orient` /
  `may_resurface`).
- **cited-proposal** — evidence cited in a governed write-proposal (`may_propose`).
- **action** — material that authorizes a bounded action or write (`may_write`).

For each candidate item, admissibility is evaluated on four axes plus a decision object:

1. admit-by sphere / scope
2. admit-by memory class
3. admit-by provenance / trust archetype + review state
4. admit-by consuming authority class
5. the admit/exclude-with-reason decision object

## Composition rule (how the axes combine)

The axes are **conjunctive and least-privilege**. An item is admitted to a given tier only if **every**
axis admits it to that tier. The admitted tier is the **lowest (most restrictive)** tier returned by
any axis ("stricter-boundary-wins"). If any axis excludes the item at every tier, the item is excluded.

> **Stricter-boundary-wins is the global fallback.** Wherever an axis input is missing, unknown, or
> ambiguous, that axis resolves to its most restrictive outcome rather than its default. Absence of a
> signal is never treated as permission.

Each axis below is stated as a **normative rule** with an explicit **default** (the outcome when the
relevant signal is present and unambiguous) and a **stricter-boundary-wins fallback** (the outcome when
it is missing or ambiguous).

## Axis 1 — admit-by sphere / scope

Resolves the admit-by-sphere open question left open in
`docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md` (§ "How explicit should sphere representation become",
residual open questions 2–3). Sphere / scope vocabulary is owned there; this axis only governs
admissibility, it does not redefine the model.

- **Rule.** A candidate item is admitted on the sphere axis when its sphere/scope membership is
  compatible with the consuming context's active operational scope.
- **Default (same-scope).** An item whose sphere/scope matches the consuming context's active
  operational scope is **admitted** on this axis (subject to the other axes).
- **Cross-sphere.** An item from a *different* sphere is admitted **only** via one of:
  - **shared participation** — the item legitimately belongs to both spheres
    (`CONTEXT_MODEL_DECISION_FRAME.md` "shared participation"); or
  - an **explicit cross-scope allowance** — a bounded, auditable runtime permission
    (`CONTEXT_MODEL_DECISION_FRAME.md` "explicit cross-scope allowance" / `bridge`).
  Absent either, a cross-sphere item is **excluded** with reason `cross_sphere_no_allowance`.
- **Stricter-boundary-wins fallback (missing scope).** When the candidate's sphere/scope is unknown or
  the consuming context's scope is undeclared, the item is **excluded** with reason
  `scope_unresolved`. Missing scope never defaults to same-scope.

## Axis 2 — admit-by memory class

Lifts the POLICY/PREFERENCE fragment currently hard-coded in `authority_guard.py`
(`_ACTION_AUTHORIZING_MEMORY_TYPES`) into a governed full-class rule across all canonical memory
classes (`app/agent_memory/candidate.py:MemoryType`). This axis governs the **inbound ceiling** by
class; the outbound escalation check in `authority_guard.py` remains authoritative for what an admitted
memory may then *do*.

Per-class maximum admissible tier (default when class is known):

| Memory class | read | cited-proposal | action | Notes |
|---|---|---|---|---|
| `WORKING_CONTEXT` | ✅ | ✅ | ❌ | ephemeral; never action-authorizing |
| `EPISODIC_MEMORY` | ✅ | ✅ | ❌ | record of events; evidence only |
| `SEMANTIC_MEMORY` | ✅ | ✅ | ❌ | derived knowledge; evidence only |
| `PROSPECTIVE_MEMORY` | ✅ | ✅ | ❌ | intentions/reminders; surfaces, does not authorize |
| `PROCEDURAL_MEMORY` | ✅ | ✅ | ❌ | must be versioned/traceable when driving repeated actions |
| `PREFERENCE_MEMORY` | ✅ | ✅ | ⚠️ | action only when also accepted-reviewed (Axis 3) and outbound `authority_guard` permits |
| `POLICY_MEMORY` | ✅ | ✅ | ⚠️ | action only when also accepted-reviewed (Axis 3) and outbound `authority_guard` permits |

- **Rule.** A memory item is admissible to a tier only if its class permits that tier per the table.
  The `⚠️` action cells are a *necessary, not sufficient* condition: the class is action-eligible, but
  the action tier additionally requires Axis 3 (accepted review) and the existing outbound
  `authority_guard` escalation check.
- **Default.** Known class → tier ceiling per the table above.
- **Stricter-boundary-wins fallback (missing/unknown class).** An item whose memory class is absent or
  unrecognized is admitted at most to **read** with reason `memory_class_unknown`; never to
  cited-proposal or action.

## Axis 3 — admit-by provenance / trust archetype + review state

Reuses the trust archetypes in `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` and the review/contradiction
lifecycle in `app/agent_memory/candidate.py` (`ReviewState`, `ContradictionState`) and
`app/context_bundles/schema.py` (`IncludedItem.trust_state` / `review_state` / `provenance`).

Minimum threshold to admit to each tier (default when provenance + review state are known):

| Archetype / state | read | cited-proposal | action |
|---|---|---|---|
| Human-authored, accepted/reviewed | ✅ | ✅ | ✅ (subject to Axes 1–2 + outbound) |
| Human-authored, raw / `UNREVIEWED` | ✅ | ✅ (cited, posture surfaced) | ❌ |
| Imported / external | ✅ | ✅ (cited, posture surfaced) | ❌ |
| Machine-proposed / derived / `inferred` | ✅ | ✅ (cited, posture surfaced) | ❌ |
| `REVISED` / superseded | ⚠️ (posture surfaced) | ❌ | ❌ |
| `REJECTED` / `CONTRADICTED` | ❌ | ❌ | ❌ |

- **Rule (the floor).** **Inferred or unreviewed material admits to read and to cited-proposal, but
  never to action.** Action requires human-authored or accepted-reviewed provenance. Cited-proposal
  admission always requires that the review/provenance posture is surfaced to the human/reviewer (no
  hidden background influence).
- **Default.** Known archetype + review state → threshold per the table.
- **Stricter-boundary-wins fallback (missing provenance).** An item with absent or unverifiable
  provenance/trust state is admitted at most to **read** with reason `provenance_unverified`; never to
  cited-proposal or action. `REJECTED`/`CONTRADICTED` material is excluded at all tiers
  (`contradicted_or_rejected`).

## Axis 4 — admit-by consuming authority class

Closes the loop: admissibility is always evaluated **relative to a declared consuming authority**. The
consuming authority is expressed as the `AuthorityFlags` posture of the consuming use (read /
propose-only / governed-execution per `docs/CAPABILITY_CONTRACT_MODEL.md`).

- **Rule — no capability may admit undeclared context.** A consuming use must declare the tier it
  admits at. An item may be admitted only up to the highest tier the consuming authority itself holds:
  a `may_answer`-only consumer admits items at **read** only; a `may_propose` consumer may admit up to
  **cited-proposal**; **action** admission requires a consumer that holds `may_write` *and* a governed
  write path (WriteGuard). The inbound predicate never raises a consumer's effective authority — it can
  only restrict it further.
- **Default.** Declared consuming authority → admission capped at the matching tier.
- **Stricter-boundary-wins fallback (undeclared consumer).** If the consuming use does not declare its
  authority, **no context is admitted** (`undeclared_consumer`). Undeclared context entering an
  undeclared consumer is the exact failure this axis forbids.

## The admissibility decision object (input-side analogue of `AuthorityFlags`)

Every evaluation produces an inspectable decision object — the input-side mirror of the outbound
`AuthorityFlags` and of the existing `IncludedItem` / `ExcludedItem` provenance records in
`app/context_bundles/schema.py`. It is normative shape, not an implementation; #2025 realizes it.

A decision records, per candidate item:

- `artifact_id` (and `path` / `chunk_ids` where applicable) — what was evaluated;
- `admitted: bool` and `admitted_tier: read | cited-proposal | action | none` — the composed outcome;
- `consuming_authority` — the declared consuming authority class the decision was made against;
- per-axis outcomes (`sphere`, `memory_class`, `provenance`, `consumer`) each as
  `admit | exclude` + the **deciding tier** and a machine-readable **reason code** (the reason codes
  named per axis above, e.g. `cross_sphere_no_allowance`, `scope_unresolved`, `memory_class_unknown`,
  `provenance_unverified`, `contradicted_or_rejected`, `undeclared_consumer`);
- `excluded` items must always carry a reason (exclusions are part of provenance, consistent with
  `CONTEXT_BUNDLE_CONTRACT.md`).

The decision object is **inspectable** (legible to human review without reading code) and
**deterministic** (the same inputs always yield the same decision), even where the cognition that later
consumes the admitted context is adaptive — consistent with the deterministic-downstream-gate stance.

## Relationship to the outbound axis (do not conflate)

- **Inbound (this contract):** *may this item ENTER?* → the admit-by predicate + decision object here.
- **Outbound (`AuthorityFlags`, `authority_guard.py`):** *what may a selected item DO?* → unchanged.

Admission is a precondition for, never a replacement of, outbound enforcement. An item admitted to the
action tier here still passes the outbound `authority_guard` escalation check and WriteGuard before any
write. This contract adds the missing front gate; it does not relitigate the back gate.

## Supersession of the #1598 documented default

The conservative three-tier influence default recorded under #1598 in
`docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` ("Bounded memory/context admissibility default")
and `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` ("Bounded context admissibility posture") is
**superseded by this contract** as the authoritative admissibility statement. Those sections remain
valid as the *influence* posture for already-admitted material and are consistent with the tiers here;
this contract is now the owner of the **admit-by** predicate they did not define. The upstream owners
cross-reference back to this contract (see those sections' supersession notes).

## Out of scope

- Runtime enforcement of the predicate — Slice #2025 (parent #2022).
- The dormant→active activation-gate flip rule — Slice #2024.
- Any capability activation — Slice #2026 (human-gated).
- Redefining the outbound `AuthorityFlags` / `authority_guard` enforcement — owned upstream, unchanged.

## Source docs

- `docs/plans/MAJOR_ROADMAP_RESET_2026_06_04.md` (Wave 5 — admissibility).
- `docs/plans/DRAFT_EXPANSION_ACTIVATION_GATE.md` (design rationale; Wave 0 admissibility deliverable).
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`, `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
  (#1598 default, now superseded for admit-by).
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`, `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md`.
- `app/context_bundles/schema.py`, `app/agent_memory/authority_guard.py`,
  `app/agent_memory/candidate.py`.
