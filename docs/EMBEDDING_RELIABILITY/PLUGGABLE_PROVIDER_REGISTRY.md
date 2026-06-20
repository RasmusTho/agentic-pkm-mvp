---
name: Pluggable Embedding Provider Registry & Selection
description: Formalize a provider registry behind EmbeddingClientProtocol with operator-selectable primary/fallback provider config
task_id: EMBEDREL-03
source_anchor: docs/EMBEDDINGS.md :: Embedding identity
parent_capability: Embedding Reliability & Pluggable Provider
prerequisites: []
depends_on: []
can_parallelize_with: [EMBEDDING_EXECUTION_QUEUE.md]
---

# Pluggable Embedding Provider Registry & Selection

## Purpose

Replace the hardcoded `if provider == "mock" / elif provider == "ollama" / raise` dispatch in `app/llm/embeddings.py::_embed_single` with a **provider registry** — a mapping from provider name to a registered adapter callable — and add **primary + fallback provider selection config** that operators can set per environment via env vars and the settings bundle. This is a pure enabling refactor: it does not change mock or Ollama behavior, does not implement the Gemini adapter (task 4), and does not wire live fallback orchestration (task 5). It makes adding a new provider a single registration + config change.

## What This Task Does

1. Defines a `ProviderAdapter` protocol/type alias — a callable with the signature `embed_one(text: str, *, model: str, dim: int, timeout: float) -> tuple[float, ...]` — in `app/llm/embeddings.py`.
2. Implements a `PROVIDER_REGISTRY: dict[str, ProviderAdapter]` dict in `app/llm/embeddings.py`, pre-populated with the existing `mock` and `ollama` adapters extracted from the current `_embed_single` branches.
3. Refactors `_embed_single` to dispatch via `PROVIDER_REGISTRY[provider](...)` instead of the if/elif chain.
4. Adds `EMBED_PRIMARY_PROVIDER` and `EMBED_FALLBACK_PROVIDER` env vars, resolved in `app/llm/embeddings.py` via new helpers `get_primary_provider()` and `get_fallback_provider()`. Fallback defaults to `None` (no-op until task 5 wires the runtime).
5. Extends `EmbeddingProfile` in `app/settings/models.py` with optional `primary_provider: str | None` and `fallback_provider: str | None` fields (both defaulting to `None`), so per-environment provider selection is possible through the settings bundle (`runtime/settings/embeddings.yaml`).
6. Extends `resolve_embedding_identity()` in `app/components/embeddings.py` to read the `primary_provider` field from the resolved profile (alongside the existing `provider` field), preserving precedence: `override_provider` > profile `primary_provider` > profile `provider` > env.
7. Updates `_SUPPORTED_EMBED_PROVIDERS` in `app/components/embeddings.py` to include `"gemini"` as a declared-but-not-yet-functional name so resolution does not silently normalize it to `"mock"` when the adapter is registered later.
8. Adds the dim guardrail: when a registered adapter is looked up, `_embed_single` still calls `assert_embed_dim` on the returned vector (unchanged from current behavior), preserving CTI-1.

This task does **not** implement the Gemini adapter, does not invoke fallback at runtime, and does not change any observable behavior for the `mock` and `ollama` paths.

## Concretely

### Registering a provider adapter

After this task, adding a provider is a one-liner registration plus the adapter function itself:

```python
# app/llm/embeddings.py

ProviderAdapter = Callable[[str, ...], tuple[float, ...]]  # conceptual

PROVIDER_REGISTRY: dict[str, ProviderAdapter] = {
    "mock": _mock_embed_one,
    "ollama": _ollama_embed_one,
    # Gemini adapter registered here by task 4:
    # "gemini": _gemini_embed_one,
}

@lru_cache(maxsize=2048)
def _embed_single(text: str, provider: str, model: str, dim: int | None) -> tuple[float, ...]:
    if dim is None:
        dim = get_embed_dim()
    if not text:
        return tuple(0.0 for _ in range(dim))
    adapter = PROVIDER_REGISTRY.get(provider)
    if adapter is None:
        raise ValueError(f"Unsupported embedding provider: {provider!r}")
    timeout = float(os.getenv("LLM_TIMEOUT", "60"))
    return adapter(text, model=model, dim=dim, timeout=timeout)
```

The existing `_ollama_embed_one` function (lines 203-217 in `app/llm/embeddings.py`) and the `_mock_vector` helper (lines 68-75) are reused as the registered adapters; no logic changes.

### Configuring primary and fallback provider

Operator sets env vars (any environment — no dev/prod feature split; only configured values differ):

```bash
# Primary provider — replaces reading LLM_PROVIDER for embedding dispatch
EMBED_PRIMARY_PROVIDER=ollama
EMBED_MODEL=nomic-embed-text:latest
EMBED_DIM=768

# Optional fallback — resolved by task 5; ignored by this task at runtime
EMBED_FALLBACK_PROVIDER=gemini
```

Or equivalently via the settings bundle `runtime/settings/embeddings.yaml`:

```yaml
default_profile: default
profiles:
  default:
    provider: ollama
    primary_provider: ollama
    fallback_provider: gemini     # declared now; wired by task 5
    model: nomic-embed-text:latest
    dim: 768
    normalize: true
```

`primary_provider` takes precedence over `provider` when both are set; `provider` remains for backward compatibility. `fallback_provider` is persisted in the profile for task 5 to read — this task stores it in the model but does not act on it at runtime.

### Dim guardrail is unchanged (CTI-1)

Every registered adapter still passes through `assert_embed_dim` in `_parse_vector` (called by `_ollama_embed_one`) or equivalent for `_mock_embed_one`. The guardrail is not moved or weakened by this refactor.

## Why This Matters

The current `_embed_single` requires editing `if/elif` branches to add any provider. The registry removes that barrier: task 4 (Gemini adapter) registers `"gemini"` without touching dispatch logic. Task 5 (fallback orchestration) reads `get_fallback_provider()` from the config wired here. Without this task, both tasks 4 and 5 would need to patch the same dispatch core — collision-prone and harder to test in isolation.

## Acceptance Criteria

- [ ] `PROVIDER_REGISTRY` exists in `app/llm/embeddings.py` with `"mock"` and `"ollama"` entries.
  - Verify: `tests/llm/test_provider_registry.py::test_registry_contains_mock_and_ollama`

- [ ] `_embed_single` dispatches via `PROVIDER_REGISTRY[provider](...)` with no remaining `if provider == "mock"` / `elif provider == "ollama"` branches.
  - Verify: `tests/llm/test_provider_registry.py::test_embed_single_dispatches_via_registry` (monkeypatches `PROVIDER_REGISTRY` with a sentinel callable and asserts it is called with correct `model`, `dim`, `timeout` kwargs)

- [ ] An unknown provider name raises `ValueError("Unsupported embedding provider: ...")` via the registry miss path, not a leftover `raise`.
  - Verify: `tests/llm/test_provider_registry.py::test_embed_single_unknown_provider_raises`

- [ ] Mock provider behavior is identical after the refactor: same deterministic hash-derived vectors, same dim, same normalization.
  - Verify: `tests/llm/test_provider_registry.py::test_mock_provider_unchanged_after_registry_refactor` (compares `embed_text` output before/after by driving `_embed_single` with `provider="mock"` against known text + dim fixture; must match current `_mock_vector` output)

- [ ] Ollama provider behavior is identical after the refactor: same HTTP calls, same payload shape, same Ollama-internal-fallback (`/api/embeddings` → `/v1/embeddings`).
  - Verify: `tests/llm/test_provider_registry.py::test_ollama_provider_unchanged_after_registry_refactor` (reuses fake-httpx pattern from `tests/llm/test_ollama_embeddings_fallback.py`; asserts identical vector output and identical call sequence)

- [ ] `EmbeddingProfile` in `app/settings/models.py` gains optional `primary_provider: str | None = None` and `fallback_provider: str | None = None` fields without breaking existing profile deserialization (existing `provider` field unchanged).
  - Verify: `tests/llm/test_provider_registry.py::test_embedding_profile_accepts_primary_and_fallback_provider_fields`

- [ ] `get_primary_provider()` and `get_fallback_provider()` helpers exist in `app/llm/embeddings.py`; `get_primary_provider()` reads `EMBED_PRIMARY_PROVIDER`, falls back to `get_provider()` (i.e., `LLM_PROVIDER`); `get_fallback_provider()` reads `EMBED_FALLBACK_PROVIDER` and returns `None` when unset.
  - Verify: `tests/llm/test_provider_registry.py::test_get_primary_provider_falls_back_to_llm_provider` and `tests/llm/test_provider_registry.py::test_get_fallback_provider_returns_none_when_unset`

- [ ] `resolve_embedding_identity()` in `app/components/embeddings.py` prefers `primary_provider` over `provider` when both are present on the resolved profile; `override_provider` still wins over both.
  - Verify: `tests/llm/test_provider_registry.py::test_resolve_embedding_identity_prefers_primary_provider_field`

- [ ] `"gemini"` is in `_SUPPORTED_EMBED_PROVIDERS` in `app/components/embeddings.py` so `_resolve_embedding_provider_name("gemini")` returns `"gemini"` (not `"mock"`).
  - Verify: `tests/llm/test_provider_registry.py::test_gemini_name_not_normalized_to_mock`

- [ ] The dim guardrail (`assert_embed_dim`) still fires when a registry-dispatched adapter returns a wrong-dim vector.
  - Verify: `tests/llm/test_provider_registry.py::test_dim_guardrail_fires_via_registry_dispatch` (registers a test-only adapter returning a fixed wrong-dim vector; asserts `ValueError` with `expected_dim` in the message, consistent with existing `test_ollama_embed_dim_mismatch_raises` in `tests/llm/test_ollama_embeddings_fallback.py`)

- [ ] No behavior change for any currently-passing test in `tests/llm/` (regression gate).
  - Verify: `pytest tests/llm/ -x` passes clean with no new failures; specifically `test_ollama_embeddings_fallback.py`, `test_provider_resolution.py`, `test_provider_fail_loud.py`, `test_embeddings_chunking.py`, and `test_embeddings_dim.py` must all remain green.

## How to Verify (Pre-Merge)

1. `pytest tests/llm/test_provider_registry.py -v` — all new tests pass.
2. `pytest tests/llm/ -x` — no regressions in existing tests.
3. Read `app/llm/embeddings.py::_embed_single`: confirm no `if provider ==` or `elif provider ==` branches remain.
4. Read `app/settings/models.py::EmbeddingProfile`: confirm `primary_provider` and `fallback_provider` fields present with `None` defaults.
5. Read `app/components/embeddings.py::_SUPPORTED_EMBED_PROVIDERS`: confirm `"gemini"` is in the set.
6. Confirm `get_primary_provider()` and `get_fallback_provider()` are exported in `app/llm/embeddings.py::__all__`.

## Out of Scope

- Implementing the Gemini adapter or any `"gemini"` embed logic (task 4 — `GOOGLE_GEMINI_ADAPTER.md`).
- Runtime fallback orchestration — actually calling `get_fallback_provider()` to route failed embeds to a secondary provider (task 5 — `PROVIDER_FALLBACK_ORCHESTRATION.md`).
- Dimension consistency recording, mixed-identity detection, or re-index migration (task 6 — `DIMENSION_CONSISTENCY_AND_REINDEX.md`).
- The bounded-concurrency queue and retry-with-backoff (task 2 — `EMBEDDING_EXECUTION_QUEUE.md`, parallelizable with this task).
- Any change to `embed_texts`, `embed_batches`, or the all-zero-batch fail-loud guard — those are unchanged.
- Hot-reload of the registry at runtime (registrations are module-level; a process restart is the expected reload path).

## Related Docs

- Normative embedding spec: `docs/EMBEDDINGS.md` (embedding identity section)
- Capability overview and CTI-1..CTI-6: `docs/EMBEDDING_RELIABILITY/README.md`
- Egress/provider-default decision: `docs/EMBEDDING_RELIABILITY/OPERATOR_EGRESS_DECISION.md`
- LLM endpoints: `docs/LLM.md`
- Settings models: `app/settings/models.py` (`EmbeddingProfile`, `EmbeddingProfiles`)
- Dispatch site: `app/llm/embeddings.py` (lines 220-241, `_embed_single`)
- Identity resolution: `app/components/embeddings.py` (`resolve_embedding_identity`, `_SUPPORTED_EMBED_PROVIDERS`)

## Related GitHub Issues

Create one bounded slice issue (`lane:agentic-lab`) covering:

- Extracting `_mock_embed_one` and confirming `_ollama_embed_one` match the `ProviderAdapter` signature
- Adding `PROVIDER_REGISTRY` and refactoring `_embed_single` to dispatch via it
- Adding `get_primary_provider()` / `get_fallback_provider()` helpers and env var reads
- Adding `primary_provider` / `fallback_provider` to `EmbeddingProfile`
- Updating `_SUPPORTED_EMBED_PROVIDERS` to include `"gemini"`
- Updating `resolve_embedding_identity()` to prefer `primary_provider`
- Writing `tests/llm/test_provider_registry.py` with all ACs above

TCD: Sonnet / high effort — refactor of the core embedding dispatch + config plumbing, regression-sensitive (must not change mock/ollama behavior).
