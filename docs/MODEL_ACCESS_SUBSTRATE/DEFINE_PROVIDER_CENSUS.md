---
name: Define Provider Census
description: Make the set of model providers defined once in docs/settings/models/providers.yaml and prove every allowlist in the repository equals its census projection.
task_id: MAS-01
source_anchor: docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md :: 2. Provider-surface census (the cross-cutting slice, first)
parent_capability: Model Access Substrate
prerequisites: []
depends_on: []
can_parallelize_with: []
---

State: Authored task specification (child issue #4287, filed 2026-07-29). Delivers R4-1, which was
specified on 2026-07-05 and never decomposed into an issue.

# Define Provider Census

## Purpose

The set of model providers is currently maintained independently at eight sites and drifts silently.
ADR-0064 §5 makes `docs/settings/models/providers.yaml` the single source for that set, with code
keeping local frozensets for hot paths and a static test asserting every allowlist equals the census
projection. This is migration step 1 and it is the mechanism that makes "adding a provider is a census
row plus a secret declaration" true instead of aspirational.

## What this task does

1. Add `docs/settings/models/providers.yaml` following the **existing** `docs/settings/models/`
   registry-plus-descriptor convention already used by `registry.yaml` and the eight model descriptor
   files. Per RUNTIME_MODEL_POSTURE §2 and ADR-0064 §3, each provider row carries: provider id, kind
   coverage (`chat` / `embedding`), tier (`local` | `paid` | `test`), supported capability flags
   (structured output, native tools, system-prompt channel, deterministic execution, and embedding
   dimension where applicable), the `paid_eligible_task_kinds` policy hook, required logical
   credential identifiers, excluded model families, and per-runtime/channel
   `capability_tier -> model` mappings. Product and Builder mappings are separate declarations.
2. Add a loader beside `app/components/settings/models_loader.py`, modelled on its
   `load_model_registry` / `load_models` pair: Pydantic models with `extra="forbid"`, a
   `DEFAULT_PROVIDER_CENSUS_PATH` constant, and the same environment-override convention as
   `MODEL_REGISTRY_PATH`. The loader is used by tests and tooling; hot paths keep their frozensets and
   gain no runtime YAML dependency.
3. Add `tests/settings/test_provider_census.py` with one parameterized test asserting every allowlist
   site equals its declared census projection, and failing with the drifted site named.
4. Add a `known_divergences` block to the census. Each entry names the site, the divergent members, a
   date, and a linked GitHub issue. An **undeclared** divergence fails the test; a declared entry
   missing either the date or the issue link also fails.
5. Validate that each tier mapping references a declared provider/model with the capabilities
   required by that mapping. Resolution policy remains owned by the named runtime; the census only
   makes the selectable set and capabilities explicit.
6. Declare the exact Phase 1 Builder Model Inquiry resolution profiles for every `dev`, `test`, and
   `prod` channel:
   - role profile `fable`, tier `frontier`, resolves to provider `anthropic`, model ref
     `claude-fable-5`, logical credential `anthropic.api-key`, and requires structured output plus a
     system-prompt channel;
   - role profile `gpt_codex`, tier `frontier`, resolves to provider `openai`, model ref
     `gpt-5.6-sol`, logical credential `openai.api-key`, and requires structured output.
   Both profiles belong to one `model-inquiry-independent-review` resolution group whose
   `independence=distinct_effective_target`; the pair must resolve to distinct
   `(provider, model, effective_identity)` tuples. These mappings are Builder policy data, not caller
   provider choices. Product mappings remain separate and unchanged.
7. Write back `docs/LLM.md :: Providers (Current)` so it points at the census as the single source
   rather than restating the set in prose.

### Sites the equality test must cover

| Site | Symbol | Current members |
| --- | --- | --- |
| `app/components/llm/router.py:42` | `_KNOWN_PROVIDERS` | `mock`, `ollama`, `openai`, `deepseek` |
| `app/components/embeddings/legacy.py:21` | `_SUPPORTED_EMBED_PROVIDERS` | `mock`, `ollama`, `openai`, `deepseek`, `deterministic`, `gemini` |
| `app/llm/embeddings.py:377-381` | `PROVIDER_REGISTRY` (keys) | `mock`, `ollama`, `gemini` |
| `app/services/llm.py:346-463` | unnamed `if/elif` ladder | `mock`, `ollama`, `openai`, `deepseek` |
| `app/llm/adapter.py:41-95` | unnamed `if/elif` ladder | `mock`, `ollama`, `openai`, `deepseek` |
| `app/cli/health.py:314-333` | `_check_llm_providers` probe set | `mock`, `ollama`, plus the raw `LLM_PROVIDER` value |
| `docs/settings/models/registry.yaml` | descriptor `provider:` values | `mock`, `ollama`, `openai` |
| `docs/LLM.md:26-31` | documented set | `ollama`, `mock`, `openai`, `deepseek`, `gemini` (planned) |

The two ladder sites have no named constant. This task extracts one per ladder — a pure rename of an
existing literal set into a module constant the ladder then reads — so the census test compares sets
rather than parsing control flow. That extraction is behaviour-preserving by construction.

`app/llm/adapter.py` remains in place. Extract its constant like the other ladder; deletion is a
separate cleanup because tests and architecture/docs surfaces still reference the module.

### Sites the test must deliberately **not** cover

Naming these prevents a well-meaning implementer from forcing unrelated sets into the census:

- `app/reasoning/provider.py:139,145` and `app/planner/provider.py:343,350` — `{"mock","golden"}` and
  `{"llm","ollama"}` are reasoning **backend** names, not provider identities.
- `app/builderops/epic_run_context_budget.py:268` — `{"luna","terra","sol"}` is a capability **tier**
  vocabulary, not a provider allowlist. Its values are used by the Builder mapping but are not forced
  to equal a provider projection.
- `app/builderops/model_inquiry_adapters.py:329` — `{"mock","fake","deterministic"}` is the Builder
  mock-identity **rejection** set, not an allowlist of servable providers.

## Concretely

```
$ python -c "from app.components.settings.providers_loader import load_provider_census; \
             print(sorted(p.id for p in load_provider_census().providers))"
['anthropic', 'deepseek', 'gemini', 'mock', 'ollama', 'openai']

$ pytest -q tests/settings/test_provider_census.py
# ... passed

# after adding "anthropic" to app/components/llm/router.py::_KNOWN_PROVIDERS only:
$ pytest -q tests/settings/test_provider_census.py
FAILED tests/settings/test_provider_census.py::test_all_allowlists_match_census[app/components/llm/router.py::_KNOWN_PROVIDERS]
  provider allowlist drift at app/components/llm/router.py::_KNOWN_PROVIDERS:
    present in site, absent from census: {'anthropic'}
```

## Why this matters

Adding `anthropic` naively means editing string sets in at least five places and missing a sixth. That
is not hypothetical: `_SUPPORTED_EMBED_PROVIDERS` already accepts `openai` and `deepseek` for which
`PROVIDER_REGISTRY` has no adapter, so a valid-looking configuration raises at runtime rather than at
config time. Without this test, every later task in this capability adds providers into a surface that
cannot tell whether it is consistent.

## Acceptance criteria

- [ ] `docs/settings/models/providers.yaml` exists and validates against a strict loader that rejects
      unknown fields.
      Verify: `tests/settings/test_provider_census.py::test_census_loads_and_rejects_unknown_fields`
- [ ] Every allowlist site listed above equals its declared census projection, and a drifted site fails
      with the site named in the failure message.
      Verify: `tests/settings/test_provider_census.py::test_all_allowlists_match_census`
- [ ] A divergence that is not declared in `known_divergences` fails the test; a declared divergence
      missing a date or a linked issue also fails.
      Verify: `tests/settings/test_provider_census.py::test_undeclared_or_unlinked_divergence_fails`
- [ ] The known divergences shipped with this task are exactly the embedding-provider gaps already
      filed as #4178 and #4181, each carrying its issue link and the date it was declared.
      Verify: `tests/settings/test_provider_census.py::test_declared_divergences_match_filed_issues`
- [ ] The extracted ladder constants are read by their ladders rather than duplicated beside them, so
      the census assertion covers the code path that actually dispatches.
      Verify: `tests/settings/test_provider_census.py::test_ladder_sites_dispatch_through_the_named_constant`
- [ ] No hot path acquires a runtime dependency on reading the census YAML.
      Verify: `tests/settings/test_provider_census.py::test_hot_paths_do_not_load_the_census_at_runtime`
- [ ] Every runtime/channel capability-tier mapping resolves to a declared provider/model whose
      capability flags satisfy the mapping, while Product and Builder mappings remain separate.
      Verify: `tests/settings/test_provider_census.py::test_runtime_channel_tier_mappings_reference_capable_declared_models`
- [ ] The exact two Builder inquiry role profiles exist for all three channels, use the declared
      Anthropic/OpenAI model and credential refs above, and the independent-review group resolves to
      distinct effective targets without caller provider/model fields.
      Verify: `tests/settings/test_provider_census.py::test_model_inquiry_role_profiles_are_exact_distinct_and_provider_free`
- [ ] `docs/LLM.md` names the census as the single provider source instead of restating the set.
      Verify: doc writeback at `docs/LLM.md :: Providers (Current)`
- [ ] `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md` records R4-1 as delivered by this task.
      Verify: doc writeback at `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md :: 5. Slices`

## How to verify (pre-merge)

- `pytest -q tests/settings/test_provider_census.py`
- `pytest -q tests/settings tests/components/llm tests/llm` — proves the extracted constants changed no
  routing or embedding behaviour
- `pytest -q -m "not pg"` — full unit lane, per the hot-path sub-agent rule
- `python3 scripts/docs_guard.py`
- Negative check performed by hand and reverted: add one provider to `_KNOWN_PROVIDERS`, confirm
  `test_all_allowlists_match_census` fails naming `app/components/llm/router.py::_KNOWN_PROVIDERS`

## Cross-task invariants preserved

INV-MAS-1 (one provider set), INV-MAS-6 (additive and behaviour-preserving), INV-MAS-7 is not touched.
Seam E is this task's own seam: the declared-divergence mechanism is the only escape hatch, and it is
tested rather than trusted.

## Out of scope

Product Anthropic routing enablement (R4-2). This task declares Anthropic for Builder execution
without adding it to Product chat execution. The `egress_posture` stage field and the budget circuit breaker
(R4-3) — the census is their declared home, but this task ships neither. The Fable-exclusion probe
(R4-4). Correcting the embedding-provider divergences themselves; they are declared here and fixed by
#4178 and #4181. The neutral intent/resolver contracts, which are MAS-04; this task supplies only
their data. Any credential value or Keychain identifier, which belongs to
`EXTEND_CREDENTIAL_CONTRACT_TO_MODEL_PROVIDERS`. Deleting `app/llm/adapter.py`.

## Related docs

- `docs/MODEL_ACCESS_SUBSTRATE/README.md` — capability contract and cross-task invariants
- `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md :: 2. Provider-surface census` — the R4-1 specification this task delivers
- `docs/adr/ADR-0064-model-access-substrate.md :: 5. One provider set`
- `docs/LLM.md :: Providers (Current)`, `docs/LLM_ROUTING.md`
- `app/components/settings/models_loader.py` — the loader convention to mirror

## Related GitHub issues

One issue. Title shape `[Model Access Substrate] define-provider-census: one provider set, enforced`.
It must state that it delivers R4-1 from `RUNTIME_MODEL_POSTURE.md §5` and must link #4178 and #4181 as
the issues backing the declared divergences. It must not absorb R4-2, R4-3, or R4-4.

TCD capability recommendation for the implementing agent: **Sonnet / high reasoning** — many sites and a
new loader, but each edit is mechanical and the test is the verifier; high rather than medium because
the declared-divergence policy is a real design choice and the ladder extraction must be proven
behaviour-preserving. R4-1's own routing note also says Sonnet
(`AGENTS.md :: Total Cost of Development`). Non-binding; `issue-to-code` re-derives it.
