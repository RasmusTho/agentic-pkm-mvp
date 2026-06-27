# Anti-Contamination Eval Fixture Corpus

Synthetic eval corpus for the Yggdrasil architecture-foundation backlog
([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551), parent epic
[#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533)). It exists to make
contamination across cognitive scopes **testable**.

## Why this corpus exists

The central validation scenario for Yggdrasil is that the system keeps **work**, **private**,
**RPG/worldbuilding**, and **general** knowledge apart even when the words are nearly identical. A
naive embedding or keyword search would happily mix these, because they all talk about *systems,
agents, state machines, events, rules, authority, memory, capabilities, and policy*. Correct behavior
must come from the architecture — `scope`, `source_role`, `authority_state`, `evidence_role`,
`CrossScopeFlow`, and retrieval admissibility — **not** from textual similarity.

This corpus is the data those tests run against. All content is **synthetic**: there is no real
private, work, client, or confidential material here.

## Scopes represented

| Group | Scope | `source_role` | `authority_state` | `evidence_role` | `sensitivity` | Expected cross-scope behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `work_project_alpha/` | `scope:work/project-alpha` | `work_project` / `decision_record` | `accepted` / `draft` | `evidence` / `background` | `internal` | Must **not** retrieve Project Beta unless an explicit, directional flow exists. |
| `work_project_beta/` | `scope:work/project-beta` | `work_project` / `decision_record` | `accepted` / `draft` | `evidence` / `background` | `internal` | Sibling of Alpha; isolated by default. |
| `private_programming/` | `scope:private/programming` | `private_note` | `draft` | `background` | `private` | Useful but **denied** into work by default; crossing needs promotion/redaction/flow. |
| `rpg_worldbuilding/` | `scope:rpg/worldbuilding` | `fictional_simulation` / `rpg_rule` | `fictional_canon` / `working_fiction` | `analogy` / `inspiration` | `private` | Fiction; usable as analogy/inspiration only when explicitly permitted. **Never** real-world evidence. |
| `general_programming/` | `scope:general/programming` | `general_knowledge` | `accepted` | `background` / `reference` | `public` | May cross as background/reference **through an explicit `CrossScopeFlow`** — never via a `general_knowledge: true` bypass. |

Each group holds 2–3 short synthetic documents. Each document begins with a small YAML frontmatter
metadata block carrying `scope_id`, `sphere`, `source_role`, `authority_state`, `evidence_role`,
`sensitivity`, and `synthetic: true`. The role/state values are drawn from the canonical value
families in [`schemas/_defs.schema.json`](../../../schemas/_defs.schema.json) (the corpus integrity
test asserts this).

## Why the vocabulary overlap is intentional

Every group deliberately reuses the same terms: **system, agent, simulation, rule, state, class,
event, workflow, authority, memory, capability, context, scope, transition, policy**. Project Alpha's
billing state machine, Project Beta's telemetry state machine, the private debugging playbook, the
Aethelgard RPG simulation, and the general concurrency notes all read as "a stateful system with
agents, events, transitions, rules, authority, and policy". This is the trap: similarity alone cannot
separate them. The only reliable signal is the metadata (scope / source_role / authority_state /
evidence_role) plus a governed `CrossScopeFlow`.

The work-project pair is intentionally the hardest case: Alpha (Atlas billing) and Beta (Borealis
telemetry) share architecture vocabulary and shape but have **different facts** and **different
scopes**, so sibling leakage is tempting and must still be denied by default.

## Invariants this corpus supports

From the [invariant registry](../../../docs/testing/invariant-tests.md):

- `rpg_not_confused_with_software` — RPG systems vs real software/system-design.
- `private_not_in_work_results` — private learning denied into work by default.
- `cross_scope_only_via_flow` / `similarity_not_permission` — overlap never authorizes crossing.
- `parent_aggregation_not_sibling_sharing` — Alpha and Beta isolated even as work "siblings".
- `retrieve_scope_prefilter` — scope/policy eligibility precedes ranking.

## Expected correct behavior: naive vs governed retrieval

- **Naive retrieval (what must NOT happen):** rank purely by embedding/keyword similarity, so an
  Aethelgard "state machine" or a private "capability pattern" surfaces inside a Project Alpha answer
  because the vocabulary matches.
- **Governed retrieval (what MUST happen):** scope/policy prefilter first; cross-scope material
  appears only when a typed `CrossScopeFlow` permits the specific operation, with the correct
  `evidence_role` in the target (general → `background`, RPG → `analogy`, private → denied by
  default). Similarity only orders the already-eligible candidates.

## How tests use it

- Static integrity checks (passing today) live in
  [`tests/evals/test_fixture_corpus.py`](../test_fixture_corpus.py): groups exist, each has enough
  docs, every doc has canonical metadata, scopes are distinguished, the shared vocabulary really does
  overlap, no real-looking identifiers, and no `general_knowledge: true` bypass.
- Behavioral retrieval/flow checks are `xfail` skeletons (runtime not implemented) in
  [`tests/evals/`](../) — they protect the invariants above until the first retrieval vertical slice
  lands. See [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552).
