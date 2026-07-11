---
name: Share Transcription Capability
description: One transcription implementation serving both the Heimdal capture path and the voice-ask path — library-level reuse inside the host, verified and contract-named, no cross-constituent runtime call and no second engine
task_id: VOICE-02
source_anchor: docs/research/yggdrasil-closed-loops-ideation.md :: 5. Mimer voice loop
parent_capability: Mimer Voice Loop
prerequisites: []
depends_on: []
can_parallelize_with: [Define Voice-Ask Contract]
---

# Share Transcription Capability

## Purpose

The capability's second hard invariant is "one transcription implementation — no fork." This task makes that true and keeps it true. **Boundary work**: it crosses the Heimdal capture path ↔ Mimer voice-ask path seam, so it names both sides and states conform/extend against the governing ADRs explicitly.

**What was actually found (spec the reality, honestly):** the transcription *engine* is **already a shared, reusable library**. `app/media/transcribe.py::run_asr` (faster-whisper, local-only, `int8`, module-level `_MODEL_CACHE`) is provider-neutral and already consumed by (a) Heimdal's capture-path glue `app/heimdal/asr_stage.py::run_asr_stage` via a lazy `from app.media.transcribe import run_asr` and (b) KAP's captionless fallback `app/knowledge_acquisition/youtube_plugin.py::_transcribe_via_asr` → `transcribe_source` → `run_asr`. The design intent is on record — "no two whisper instances", `docs/HEIMDAL/FABLE_COMPANION.md` §5.2 / §9-j. **Therefore this is primarily a verification + contract-naming task, not a build-a-shared-lib task.** It does not create a new engine; it names the seam, adds the third consumer (voice-ask) to it, and installs the fitness test that stops a fork.

## What This Task Does

1. **Names both sides of the seam** in a short contract note (in this spec dir and cross-linked from the client contract / Heimdal docs):
   - **Heimdal capture path** (Heimdal sensor constituent, ADR-0043): `asr_stage.run_asr_stage` — transcribes a **persisted, governed raw capture** read through the raw-read gate (`app/heimdal/raw_read_gate.read_raw_record(reader="asr_stage")`), with confidence shaping, multi-speaker guard, and a replay ledger. Produces a Heimdal transcript record.
   - **Mimer voice-ask path** (Mimer interface surface, HIX): VOICE-01's endpoint — transcribes an **ephemeral query utterance** on an in-memory temp WAV, deleted after, **not** through the Heimdal raw-read gate and producing **no** raw record. This distinction is load-bearing for the capability's read-only invariant: a spoken *question* is not a *capture*.
   - **Shared engine** (host infrastructure): `app/media/transcribe.py::run_asr` + `_MODEL_CACHE` — the one place the whisper model runs, for both paths and KAP.
2. **Adds the voice path as a first-class consumer** of the shared engine — a thin voice-side call (its own ephemeral-WAV handling, no Heimdal gating, no confidence/ledger machinery) that reaches `run_asr` directly, mirroring how `transcribe_source` reaches it for KAP. No Heimdal code changes; no engine changes.
3. **Installs the no-fork fitness test** — asserts (a) the voice path resolves to `app/media/transcribe.py::run_asr` and not any other transcriber, and (b) the module set that imports a whisper/ASR engine is exactly `{app/media/transcribe.py}` (one model owner), so a second `WhisperModel`/`faster_whisper` instantiation anywhere on the voice path fails CI naming the site. This is the mechanism that keeps invariant 2 true after the engine's authors have moved on.
4. **Confirms language + posture parity** — both paths inherit auto-detected language (no `language=` pin) and the local-only, fail-loud posture (`LocalAsrUnavailableError`, no cloud fallback), so the voice path cannot silently acquire a different STT provider or a cloud egress the capture path forbids.

## Concretely

```
$ pytest -q tests/voice/test_transcription_sharing.py
# asserts: voice path calls app.media.transcribe.run_asr; exactly one module owns a whisper engine.
$ python - <<'PY'
import app.media.transcribe as t
print(t.run_asr.__module__)     # app.media.transcribe  (the one engine, shared)
PY
```

## Why This Matters

If the voice path grows its own transcriber, the system pays for two whisper model loads, drifts on language/confidence behavior between "what Heimdal heard" and "what voice-ask heard", and can silently acquire a cloud STT the capture path deliberately refuses — breaking the local-only posture without anyone deciding to. Naming the seam also protects the read-only invariant: without the explicit capture-vs-query distinction, a future refactor could route voice-ask audio through the Heimdal raw-read/capture machinery and turn every spoken question into a governed capture.

## SBS Impact — boundary work (both sides named)

- **Sides:** Heimdal sensor constituent (capture path) ↔ Mimer interface (voice-ask path), sharing host infrastructure (`app/media/transcribe.py`). This is **library-level reuse inside one host, not a cross-constituent runtime call** — both consumers import the engine in-process; no network/IPC boundary is crossed and no constituent runtime calls another.
- **Conform / extend against the ADRs (explicit):**
  - **ADR-0043 (Heimdal = sensor constituent; Norse register): CONFORM.** This task reassigns no name and moves no ownership. Heimdal keeps owning the *capture* transcription stage; the shared engine stays host infrastructure; voice-ask is a Mimer interface consuming the same engine. It does **not** make voice-ask a Heimdal capture (the read-only / no-raw-record distinction is exactly what keeps the constituent boundary honest).
  - **ADR-0055 (multi-writer vault consistency): NO EFFECT / CONFORM.** Transcription on the voice path writes nothing to the vault — the transcript is an in-memory string handed to ASK. No new writer class, no note-class change. (The loop's only vault write is VOICE-04's append-only transcript, which conforms to ADR-0055's append-only class; it is not this task's concern.)
  - **ADR-0056 (client contract + transport set): CONFORM.** The engine is not a client transport; it is internal. VOICE-01 adds the *endpoint* to the contract's HTTP-API transport; this task adds no transport and reopens nothing (ADR-0047 MCP deferral untouched).
- **No reshape.** No boundary, charter, contract, or ADR is altered; the single design fact being formalized (one shared ASR engine) already ships and is already the recorded intent (`FABLE_COMPANION` §5.2/§9-j).

### Implemented voice-side seam

`app/voice/transcription.py::transcribe_voice_wav` is the Mimer-side adapter.
It writes the request's WAV bytes only to a temporary `.wav`, calls
`app.media.transcribe.run_asr` directly, then deletes the file in `finally`.
It does not import or call the Heimdal raw-read gate, create a raw record, or
own a Whisper model. Local-engine failure is surfaced as
`LocalAsrUnavailableError`; there is no cloud fallback or language pin.

## Acceptance Criteria

- [ ] AC1 (enforcement): the voice-ask path resolves its transcription to `app/media/transcribe.py::run_asr` — asserted at the voice path's production call site, not merely that `run_asr` exists. Verify: `tests/voice/test_transcription_sharing.py::test_voice_path_calls_shared_run_asr`
- [ ] AC2 (enforcement, no-fork): exactly one module in `app/` instantiates a whisper/faster-whisper engine; a second instantiation on the voice path (or anywhere) fails and names the site. Verify: `tests/voice/test_transcription_sharing.py::test_single_asr_engine_owner`
- [ ] AC3: the voice path uses an **ephemeral** temp WAV deleted after transcription and does **not** invoke the Heimdal raw-read gate (`read_raw_record`) — a voice question produces no Heimdal raw record. Verify: `tests/voice/test_transcription_sharing.py::test_voice_path_is_ephemeral_and_ungated`
- [ ] AC4: language auto-detection and local-only/fail-loud posture parity — the voice path pins no `language=` and inherits `LocalAsrUnavailableError` semantics (no cloud fallback). Verify: `tests/voice/test_transcription_sharing.py::test_voice_path_posture_parity`
- [ ] AC5 (contract doc): the seam note names Heimdal capture path, Mimer voice-ask path, and the shared engine, with the conform/extend classification above. Verify: doc writeback at `docs/MIMER_VOICE_LOOP/SHARE_TRANSCRIPTION_CAPABILITY.md :: SBS Impact — boundary work (both sides named)` (and a cross-link line added under `docs/contracts/MIMER_CLIENT_CONTRACT.md :: 11. References`)

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/voice/test_transcription_sharing.py
pytest -q tests/heimdal/test_asr_stage.py     # confirm the capture path is untouched (regression guard)
pytest -q -m "not pg"
```

## Out of Scope

Extracting `run_asr` into a dedicated `app/media/asr_engine.py` module (the `FABLE_COMPANION` §5.2 proposal — desirable tidy-up but not required for one-engine correctness; if done, it must not add a second engine and this task's tests move with it); any Heimdal capture-path change; diarization/speaker-id; a cloud STT provider (the local-only posture is a floor, not a v1 choice); the voice endpoint itself (VOICE-01).

## Related Docs

- `app/media/transcribe.py` (`run_asr`, `_MODEL_CACHE`, `transcribe_source`); `app/heimdal/asr_stage.py` (`run_asr_stage`, the capture-path consumer); `app/knowledge_acquisition/youtube_plugin.py::_transcribe_via_asr` (the KAP consumer precedent)
- `docs/HEIMDAL/FABLE_COMPANION.md` §5.2 (shared ASR engine, "no two whisper instances"), §9-j (owner-directed shared ASR), §5.1/§9-k (voice memo is a Heimdal capture; Heimdal-as-ingestion-organ); ADR-0049 (Heimdal ingestion organ + ASR stage)
- `docs/KNOWLEDGE_ACQUISITION/ASR_FALLBACK_PATH.md` ("reuse, not rewrite" precedent); ADR-0043 (constituent register); `docs/architecture/SBS_OPERATING_MODEL.md` §3 (boundary-work classification)

## Related GitHub Issues

One issue: `[Mimer Voice Loop] share-transcription: one ASR engine for capture + voice-ask, verified no-fork`. `agent:ready` immediately (no prerequisites; parallelizable with VOICE-01). TCD hint: **opus, high reasoning** — boundary work across a constituent seam with three explicit conform/extend claims and a fitness-guarantee (no-fork) that has a high blast radius if the boundary reasoning is wrong; getting the capture-vs-query distinction and the ADR classification right is worth the opus tier even though the code delta is small.
