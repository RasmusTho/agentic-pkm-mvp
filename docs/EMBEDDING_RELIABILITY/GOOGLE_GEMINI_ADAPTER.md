---
name: Google Gemini Embedding Adapter
description: Gemini gemini-embedding-001 with output_dimensionality=768 (L2-renormalized) provider adapter with env-only secret handling, registered in the provider registry
task_id: EMBEDREL-04
source_anchor: docs/EMBEDDING_RELIABILITY/OPERATOR_EGRESS_DECISION.md :: Secret handling
parent_capability: Embedding Reliability & Pluggable Provider
prerequisites: [EMBEDREL-03]
depends_on: [PLUGGABLE_PROVIDER_REGISTRY.md]
can_parallelize_with: []
---

# Google Gemini Embedding Adapter

## Purpose

Implement a Google Gemini embedding adapter that integrates with the pluggable provider registry (EMBEDREL-03) and satisfies the operator egress posture defined in `OPERATOR_EGRESS_DECISION.md`. The adapter makes Gemini available as a registered provider — using `gemini-embedding-001` with `output_dimensionality=768` (L2-renormalized to match the existing nomic-embed-text 768 index) — while ensuring the key is sourced exclusively from the environment, never committed or logged, and that the adapter is simply unavailable (not crashed) when no key is configured, so local-only deployments stay fully viable.

Note: `text-embedding-004` was retired (deprecated January 14, 2026); the active models are `gemini-embedding-001` (stable, text) and `gemini-embedding-2` (newest, multimodal). Both default to 3072 dims and support `output_dimensionality` (range 128–3072). This capability pins `gemini-embedding-001` at 768 via `output_dimensionality=768`; because the dim is non-default, the adapter must L2-renormalize the returned vector (`gemini-embedding-2` auto-renormalizes but is not pinned here). `gemini-embedding-2` may be substituted by changing `EMBED_GEMINI_MODEL` and switching to that model's endpoint.

## What This Task Does

1. Adds `app/llm/gemini_embeddings.py` — an httpx-based Gemini embedding adapter following the same HTTP call style as the existing Ollama adapter in `app/llm/embeddings.py` (`httpx.post`, `_extract_error_detail`, `_parse_vector`, `assert_embed_dim`, timeout via `LLM_TIMEOUT`).
2. Registers the adapter under the `"gemini"` provider name in the provider registry (EMBEDREL-03) with the `GeminiEmbeddingAdapter` class implementing `EmbeddingClientProtocol` from `app/components/embeddings.py`.
3. Adds `"gemini"` to `_SUPPORTED_EMBED_PROVIDERS` in `app/components/embeddings.py` (line 14).
4. Wires `"gemini"` into `_embed_single` in `app/llm/embeddings.py` (or the equivalent registry dispatch introduced by EMBEDREL-03) so that `embed_text(provider="gemini", ...)` routes to the adapter.
5. Makes the Gemini provider probeable via `app/cli/embed_probe.py` — `embed-probe --profile gemini` (or `--provider gemini` if EMBEDREL-03 introduces that flag) should reach the adapter; with no key set it should report unavailable rather than crash.
6. Adds `tests/llm/test_gemini_embeddings.py` — all tests mock httpx; no real network calls or real key required in CI.

This task does NOT wire the Ollama-primary → Gemini-fallback decision path; that is EMBEDREL-05 (`PROVIDER_FALLBACK_ORCHESTRATION.md`).

## Concretely

### Happy path — key configured

```
GEMINI_API_KEY=<real-key> EMBED_DIM=768 embed-probe --profile gemini
Sample 'Hello world': provider=gemini model=gemini-embedding-001 dim=768 normalize=True norm=1.0000
Sample 'Det här är ett svenskt exempel': provider=gemini model=gemini-embedding-001 dim=768 normalize=True norm=1.0000
Sample 'Agentic PKM system': provider=gemini model=gemini-embedding-001 dim=768 normalize=True norm=1.0000
Provider profile=gemini provider=gemini model=gemini-embedding-001 dim=768 normalize=True
```

### Override model via env

```
GEMINI_API_KEY=<real-key> EMBED_GEMINI_MODEL=gemini-embedding-001 embed-probe --profile gemini
# identical output — EMBED_GEMINI_MODEL default is gemini-embedding-001, so this is a no-op override
```

### No-key unavailable path

```
# GEMINI_API_KEY and GOOGLE_API_KEY both unset
embed-probe --profile gemini
# exits with a clear error: "gemini unavailable: no API key configured (set GEMINI_API_KEY or GOOGLE_API_KEY)"
# does NOT crash the worker; the fallback orchestrator (EMBEDREL-05) treats this as UNAVAILABLE, not TRANSIENT
```

### Dim guardrail — wrong-dim response caught

If the Gemini API returns a vector of length != 768 (misconfigured model, API drift), `assert_embed_dim` raises and the object surfaces `index.embedding.failed`. The index is never silently corrupted with wrong-dim vectors (CTI-1).

### Model note

`gemini-embedding-001` is the active model pinned by this capability (default dim 3072; this adapter requests `output_dimensionality=768`). `gemini-embedding-2` is a newer multimodal model that also defaults to 3072 and supports `output_dimensionality`; unlike `gemini-embedding-001`, it auto-renormalizes for non-default dims so explicit L2-renormalization would be redundant. Switching to `gemini-embedding-2` (or switching to the full 3072 default dim of either model) would change the embedding identity and require a full VectorIndex re-index (CTI-1 / `docs/EMBEDDINGS.md :: Why identity matters`). Record any such switch as a future re-index-only upgrade path, not a task for this slice.

## Why This Matters

The operator chose Gemini as the auto-fallback provider specifically to handle Ollama OOM failures on the mac mini (README.md § Decided posture). Without this adapter, the fallback chain (EMBEDREL-05) has nothing to route to and the full-vault ingest still aborts when Ollama crashes. This adapter is the prerequisite that makes fallback a runnable option — and the secret-gated design is what keeps the local-only path viable for anyone who does not configure a key.

## Acceptance Criteria

- [ ] `app/llm/gemini_embeddings.py` exists and implements `embed_gemini_text(text, *, model, dim, timeout, base_url) -> tuple[float, ...]` following the httpx call pattern in `app/llm/embeddings.py` (no `requests`, no `google-generativeai` SDK dependency). The implementation requests `output_dimensionality=768` in the API payload, then L2-renormalizes the returned 768-element vector before returning (required for non-default dims with `gemini-embedding-001`).
  - Verify: `tests/llm/test_gemini_embeddings.py::test_embed_gemini_text_happy_path` — mocks `httpx.post` returning a 768-element response, asserts returned tuple length == 768, `assert_embed_dim` called, and the returned vector is L2-normalized (norm ≈ 1.0).
- [ ] API key is resolved as `GEMINI_API_KEY` (preferred) then `GOOGLE_API_KEY`; if neither is set the adapter raises `GeminiUnavailableError("gemini unavailable: no API key configured (set GEMINI_API_KEY or GOOGLE_API_KEY)")` before making any network call.
  - Verify: `tests/llm/test_gemini_embeddings.py::test_no_api_key_raises_unavailable` — with both env vars unset, constructing or calling the adapter raises `GeminiUnavailableError`; `httpx.post` is never called.
- [ ] HTTP 429 and 5xx responses raise a `GeminiTransientError` (a subclass or tagged exception that the queue in EMBEDREL-02 can classify as TRANSIENT for retry/backoff). HTTP 4xx (bad key, auth failure) raise a `GeminiAuthError` (non-transient).
  - Verify: `tests/llm/test_gemini_embeddings.py::test_http_429_raises_transient`, `test_http_500_raises_transient`, `test_http_401_raises_auth_error` — each mocks `httpx.post` returning the relevant status code.
- [ ] Network / connection errors (`httpx.ConnectError`, `httpx.TimeoutException`) raise `GeminiTransientError`.
  - Verify: `tests/llm/test_gemini_embeddings.py::test_network_error_raises_transient` — mocks `httpx.post` side-effect as `httpx.ConnectError`.
- [ ] The request payload follows the Generative Language **REST** `embedContent` schema (raw httpx, not the Python SDK): `{"model": "models/gemini-embedding-001", "content": {"parts": [{"text": <text>}]}, "embedContentConfig": {"outputDimensionality": 768}}`. The dimensionality field is **camelCase `outputDimensionality` nested under `embedContentConfig`** (the deprecated top-level field is not used) — snake_case `output_dimensionality` is the SDK form and would be ignored by REST, causing the API to return the default 3072-dim vector. The response vector is extracted from `embedding.values`; length is validated via `assert_embed_dim(vector, expected=768, name="embedding")`; the vector is L2-renormalized before return (required for `gemini-embedding-001` at non-default dims). REST ref: https://ai.google.dev/api/embeddings#EmbedContentConfig
  - Verify: `tests/llm/test_gemini_embeddings.py::test_request_payload_format` — asserts `httpx.post` call args match the expected endpoint and JSON body, specifically `embedContentConfig.outputDimensionality == 768` (camelCase, nested); `test_response_vector_extracted_from_embedding_values` — asserts extraction from `{"embedding": {"values": [...]}}` and that the returned vector is L2-normalized (norm ≈ 1.0).
- [ ] Dim guardrail: if the API returns a vector whose length != 768 (i.e., the `embedContentConfig.outputDimensionality=768` request was ignored and the model's default 3072 was returned), `assert_embed_dim` raises and the caller receives a `ValueError` (not a silent wrong-dim vector). This guards against API drift where the dimensionality parameter is not honoured.
  - Verify: `tests/llm/test_gemini_embeddings.py::test_wrong_dim_raises_value_error` — mocks a 3072-element response vector (simulating the API ignoring `outputDimensionality`), asserts `ValueError` raised.
- [ ] `"gemini"` is added to `_SUPPORTED_EMBED_PROVIDERS` in `app/components/embeddings.py` (line 14 in the current file).
  - Verify: `tests/components/test_embeddings.py::test_gemini_in_supported_providers` — asserts `"gemini" in _SUPPORTED_EMBED_PROVIDERS`.
- [ ] `EMBED_GEMINI_MODEL` env var controls the model name (default `gemini-embedding-001`); an optional `GEMINI_BASE_URL` env var overrides the API base URL (for test isolation).
  - Verify: `tests/llm/test_gemini_embeddings.py::test_embed_gemini_model_env_override` — sets `EMBED_GEMINI_MODEL=custom-model`, asserts request uses that model; `test_gemini_base_url_override` — sets `GEMINI_BASE_URL`, asserts httpx.post targets that base.
- [ ] The API key is NEVER written to any log line, event payload, or exception message. Note content (the `text` argument) is NEVER logged beyond existing provenance fields.
  - Verify: `tests/llm/test_gemini_embeddings.py::test_key_not_logged` — captures `logging` output during a mock adapter call (happy path, transient error, auth error) and asserts the key value does not appear in any log record; `test_text_not_logged` — asserts the text argument value does not appear in log records.
- [ ] `embed-probe --profile gemini` (or the equivalent provider-override flag introduced by EMBEDREL-03) reaches the adapter when a key is set and exits non-zero with a clear "unavailable" message when no key is set.
  - Verify: `tests/cli/test_embed_probe.py::test_probe_gemini_provider_no_key` — invokes the probe CLI with the gemini provider and both key env vars unset; asserts exit code != 0 and stderr contains "gemini unavailable".

## How to Verify (Pre-Merge)

1. Run `pytest tests/llm/test_gemini_embeddings.py -v` — all tests pass with mocked httpx; no network calls.
2. Run `pytest tests/components/test_embeddings.py::test_gemini_in_supported_providers -v`.
3. Run `pytest tests/cli/test_embed_probe.py::test_probe_gemini_provider_no_key -v`.
4. Confirm no import of `google-generativeai` or `google.generativeai` anywhere in the new files (the adapter uses httpx only, matching the Ollama adapter style).
5. Grep for the test API key value used in fixtures — it must not appear in any log output captured by the test suite.
6. Confirm `_SUPPORTED_EMBED_PROVIDERS` in `app/components/embeddings.py` contains `"gemini"`.

## Out of Scope

- Wiring the Ollama → Gemini fallback decision (EMBEDREL-05, `PROVIDER_FALLBACK_ORCHESTRATION.md`).
- Switching to the full 3072 default dim of `gemini-embedding-001` or switching to `gemini-embedding-2` — either change requires a full VectorIndex re-index and is a future re-index-only upgrade path.
- Rate-limiting or retry/backoff logic — the queue (EMBEDREL-02) owns that; this adapter makes one call and maps errors.
- Changing `docs/EMBEDDINGS.md :: Fallback rule` — that update belongs to EMBEDREL-06 (`DIMENSION_CONSISTENCY_AND_REINDEX.md`) and EMBEDREL-01 (`OPERATOR_EGRESS_DECISION.md`), both already filed.
- Adding `google-generativeai` or any non-httpx Google SDK as a dependency — the adapter must be pure httpx to match the existing style and avoid a transitive dependency upgrade.
- Multi-modal or non-text embedding paths.

## Related Docs

- `docs/EMBEDDING_RELIABILITY/OPERATOR_EGRESS_DECISION.md` — operator decision + secret env var choices
- `docs/EMBEDDING_RELIABILITY/README.md` — CTI-1 (dim guardrail) and CTI-4 (secret-gated egress)
- `docs/EMBEDDINGS.md` — normative embedding spec; embedding identity, dim guardrail, fallback rule
- `app/llm/embeddings.py` — existing Ollama adapter to match in style (httpx.post, _extract_error_detail, _parse_vector, assert_embed_dim, LLM_TIMEOUT)
- `app/components/embeddings.py` — `EmbeddingClientProtocol`, `EmbeddingIdentity`, `_SUPPORTED_EMBED_PROVIDERS`
- `app/llm/endpoints.py` — endpoint resolution pattern for reference
- `app/cli/embed_probe.py` — probe CLI that must reach the adapter
- `docs/EMBEDDING_RELIABILITY/PLUGGABLE_PROVIDER_REGISTRY.md` — EMBEDREL-03, the registry this adapter registers into (prerequisite)
- `docs/EMBEDDING_RELIABILITY/PROVIDER_FALLBACK_ORCHESTRATION.md` — EMBEDREL-05, the downstream task that wires Ollama→Gemini routing

## Related GitHub Issues

Create one bounded implementation slice issue (lane: Core Runtime) for this adapter. No docs-lane split is needed — the adapter ships code and a registration change only; doc anchors already exist in EMBEDREL-01.

TCD: Sonnet / high effort — external API + secret handling + dim guardrail; security-sensitive (data egress), so review gate matters.
