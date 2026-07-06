State: Operator runbook for the BGE-M3 primary-embedding-model cutover (not yet executed).
Doc role: Operations runbook
Authority: Step-by-step activation + re-index procedure; the identity/dimension contract is
`docs/EMBEDDINGS.md` and `docs/adr/ADR-0052-embedding-fallback-repin-1024-bge-m3.md`.
Owner: Retrieval / embedding posture
Temporal class: operational (execute once per environment at cutover time; re-run per environment
independently — dev, then test, then prod)

# Runbook — BGE-M3 primary embedding model cutover (dev → test → prod)

Mechanism issue: #2984 (G3-1, H4). Decision record: `docs/adr/ADR-0052-embedding-fallback-repin-1024-bge-m3.md`
(Accepted). Contract: `docs/EMBEDDINGS.md`. This runbook is the **actual cutover procedure** the
mechanism issue intentionally did not execute — #2984 shipped the BGE-M3 profile as a SELECTABLE
mechanism (`app/settings/models.py::EmbeddingProfiles.profiles["bge-m3"]`) without flipping the live
runtime default, specifically so this cutover stays an explicit, operator-timed action per
environment. **Do not run the prod steps below without a recorded operator acknowledgment first**
(standing rule, restated at the prod section).

## Why this is not automatic

- The shipped runtime default remains `nomic-embed-text` @ 768 dims. Flipping it silently would
  break live retrieval immediately: a 1024-dim query against a 768-dim stored index (or vice versa)
  fails `assert_embed_dim` at the query embedding step and/or serves stale/incomparable vectors.
- BGE-M3 must be present in the target Ollama instance before any embed call using it can succeed.
- Every dimension change requires a **full re-index** (`docs/EMBEDDINGS.md :: Dim-change re-index`) —
  reconcile (`index reconcile`) only converges same-dimension mixed identities; it cannot bridge a
  768→1024 dimension change.

## Preconditions (all environments)

1. Confirm ADR-0052 is Accepted (it is, as of 2026-07-06) and `docs/EMBEDDINGS.md` reflects the
   `bge-m3` profile (post-#2984 merge).
2. Confirm the target Ollama instance can pull the model:
   `ollama pull bge-m3`
   Verify: `ollama list | grep bge-m3`
3. Confirm `GEMINI_API_KEY` / `GOOGLE_API_KEY` fallback (if configured) will re-pin automatically —
   no separate action needed; the Gemini adapter passes through whatever `dim` the primary resolves
   to (see `app/llm/gemini_embeddings.py::_gemini_embed_one`), so once the primary identity moves to
   1024 the fallback follows without a config change.

## Cutover steps (run once per environment)

### 1. Activate the profile

Set the environment's config to select `bge-m3` instead of the shipped default. Either:

- Env var (simplest, no file change): `EMBED_PROFILE=bge-m3`
- Or `runtime/settings/embeddings.yaml`: `default_profile: bge-m3`

Also set the raised input-char budget the profile recommends for BGE-M3's larger context window
(this is advisory metadata on the profile, not auto-applied — see `docs/EMBEDDINGS.md ::
EMBED_MAX_INPUT_CHARS`):

```
EMBED_MAX_INPUT_CHARS=24000
```

Do **not** also set `EMBED_MODEL` / `EMBED_DIM` explicitly unless overriding the profile — the
`bge-m3` profile already carries `model=bge-m3`, `dim=1024`, `normalize=true`, `no_prefix=true`.

### 2. Confirm the resolved identity before touching the index

```
python -m app.cli health   # or your environment's health/status entrypoint
```

Verify the reported embedding identity is now `{provider: ollama, model: bge-m3:latest, dim: 1024}`
and NOT the old `nomic-embed-text` identity, before running any index command. If it still reports
the old identity, the profile activation (step 1) did not take effect in this process — check env
var scoping / restart the process picking up the new config.

### 3. Full re-index

This is a **dimension change**, so it is a destructive full rebuild, not a reconcile
(`docs/EMBEDDINGS.md :: Dim-change re-index`). `index rebuild` auto-detects the identity change and
resets the Postgres vector index (drops + re-creates `store_vector_index` under the new identity)
before re-embedding every object — no separate manual `reset_vector_index` step is required:

```
python -m app.cli index rebuild --profile bge-m3 --json
```

For a large corpus, consider `--limit` to stage the run, or run unattended with `--strict` so a
non-zero exit is visible to your process supervisor. Review the emitted summary for
`errors`/`failures-path` entries — an oversized or pathological note degrading to a per-item failure
does not abort the whole run (see `docs/EMBEDDINGS.md :: Oversized input handling`), but a
non-trivial failure count should be investigated before declaring the environment migrated.

### 4. Doctor-verify single identity

```
python -m app.cli index doctor --strict
```

Verify:
- `rebuild_required: false`
- exactly one identity reported (no `mixed_identities` beyond one entry / no "Mixed embedding
  identities" issue)
- no `index.embedding.failed` events pending

If doctor still reports a mixed index (some objects failed to re-embed, or ingestion landed new
objects mid-rebuild), run:

```
python -m app.cli index reconcile --json
```

This converges any remaining non-primary-identity rows (now a same-dimension operation, since the
primary identity is now 1024 throughout) without a second destructive rebuild.

### 5. Verify retrieval / ASK uses the new identity

Run a representative ASK query against the environment and confirm results are non-empty and
qualitatively sane (this environment's existing smoke/UAT path, e.g. `docs/EMBEDDING_RELIABILITY/`
or the environment's own smoke script). The RAG invariant (`docs/EMBEDDINGS.md :: Query vs Document
embeddings`) requires the query path to resolve the same identity as the documents — this is
automatic once the profile is active process-wide (both paths call the same `get_embedding_client` /
`resolve_embedding_identity`), but confirm empirically rather than assuming.

## Environment order and gating

1. **Dev vault first.** Run steps 1–5 against the dev environment/vault. Confirm clean before
   proceeding.
2. **Test channel next.** Repeat against the test channel (`vault-test/`, `app_test` DB). Confirm
   clean before proceeding.
3. **Prod — operator-ack-gated.** Do **not** run steps 1–5 against prod without an explicit,
   recorded operator acknowledgment (standing rule; not a per-slice judgment call). Record the
   acknowledgment as an issue comment or ops log entry referencing this runbook and #2984 before
   executing. Prod re-index is a full rebuild of the live `store_vector_index` — treat it with the
   same care as any other irreversible-in-practice migration (`docs/RELEASE_CHANNELS/README.md`,
   `docs/ENVIRONMENTS.md`).

## Rollback

There is no in-place rollback for a completed dim-change rebuild (the old-dimension vectors are
gone once step 3 completes for an object). To roll back:

1. Revert the profile activation (unset `EMBED_PROFILE` / revert `default_profile`) so the resolved
   identity returns to the shipped `nomic-embed-text` @ 768 default.
2. Run `python -m app.cli index rebuild --profile default --json` to re-index back under the old
   identity (also a destructive full rebuild, symmetric to the forward cutover).
3. Doctor-verify per step 4 above.

Because rollback itself requires a full re-index, prefer running step 3 (forward cutover) against a
disposable/staged copy of the target environment first, or during a low-traffic window, rather than
relying on rollback as a fast escape hatch.

## What this runbook does not cover

- BM25-folding into BGE-M3 sparse output — explicitly out of scope (README owner decision 6).
- The SV/EN retrieval quality eval that validates the migration's actual impact — tracked separately
  (H5), not a precondition for this runbook per the owner's R2 ruling ("switch to BGE-M3 now, measure
  after").
- G5 fusion/rerank tuning — separate track, not filed yet.
