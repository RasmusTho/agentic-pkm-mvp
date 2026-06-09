State: Current Companion UI local-first TTS contract.
Doc role: Runtime API contract / local setup contract
Authority: Defines the shipped local-only TTS planning and synthesis boundary for Companion UI read-back.
Owner: Companion UI / runtime integration
Temporal class: operational
Review cadence: event-driven
Source of truth: code + local runtime setup
Last reviewed: 2026-06-08
Last verified against: `app/tts/**`, `tests/tts/test_tts_planning.py`, `tests/tts/test_tts_cache.py`, `tests/api/test_companion_tts_api.py`, `tests/companion_ui/test_tts_readback.py`

# Local-First TTS Contract

Companion UI read-back uses server-side local TTS by default. Browser/system TTS is not the default
path, and cloud TTS fallback is not part of this contract.

## Runtime Boundary

Endpoints:

- `POST /api/companion/tts/plan`
- `POST /api/companion/tts/synthesize`
- `GET /api/companion/tts/status`
- `GET /api/companion/tts/audio/{cache_key}.wav`

The plan endpoint normalizes text, skips fenced code blocks, detects or honors language, selects a
local voice provider, and returns a cache key plus provider availability, cache status, segments,
and warnings. It does not generate audio.

Requests whose text is empty after Markdown/text normalization are invalid for both planning and
synthesis. The API rejects normalized-empty input before provider selection, cache-key generation,
plan persistence, audio URL construction, or provider availability reporting.

The synthesize endpoint first checks the audio cache. If cached audio exists, it returns the cached
audio URL without invoking a provider. If audio is not cached, it invokes a local provider only when
`TTS_ENABLED=true`, `TTS_LOCAL_ONLY=true`, local model files exist, and the provider command is
available.

The audio route serves only cache-key-addressed WAV files from `TTS_CACHE_DIR`. It does not expose
absolute filesystem paths.

The status endpoint reports active local-only/fallback policy, configured model/cache/log paths,
whether those paths are outside the repo, provider/model availability for Piper `sv-SE` and Kokoro
`en-US` / `en-GB`, cache size/eviction policy, path writability, and the Mac mini operator receipt
path. The receipt path records runtime path/config evidence only; generated audio remains in the
cache and must not be written to the repo.

## Required Local Environment

The Mac mini Companion UI host keeps runtime TTS state outside the repo:

```text
TTS_ENABLED=true
TTS_LOCAL_ONLY=true
TTS_MODEL_DIR=/Volumes/T7/CompanionData/tts/models
TTS_CACHE_DIR=/Volumes/T7/CompanionData/tts/cache
TTS_LOG_DIR=/Volumes/T7/CompanionData/tts/logs
TTS_CACHE_MAX_GB=2
TTS_CACHE_EVICTION=lru
TTS_MAX_CONCURRENT_JOBS=1
TTS_MAX_CHARS_PER_REQUEST=4000
TTS_ALLOW_BROWSER_FALLBACK=false
TTS_ALLOW_CLOUD_FALLBACK=false
```

Model files and generated audio must not be stored in the repo. The external layout is:

```text
/Volumes/T7/CompanionData/tts/
  models/
    piper/
    kokoro/
  cache/
    audio/
    plans/
  logs/
```

## Provider Selection

- `sv-SE` uses Piper voice `sv_SE-nst-medium`.
- `en-US` uses Kokoro voice `af_heart`.
- `en-GB` uses Kokoro voice `bf_emma`.

Provider commands are local executables only:

- Piper: `TTS_PIPER_COMMAND` or `piper` on `PATH`.
- Kokoro: `TTS_KOKORO_COMMAND` or `kokoro` on `PATH`; when no command exists, the optional
  local `kokoro_onnx` Python package can synthesize from `kokoro-v1.0.int8.onnx` and
  `voices-v1.0.bin`.

If a command is missing, the API reports the provider as unavailable instead of falling back to
browser/system TTS or a cloud API.

## Cache and Logs

The cache is bounded by `TTS_CACHE_MAX_GB` and `TTS_CACHE_EVICTION=lru`. Cleanup is deterministic
least-recently-used over cache artifacts under `TTS_CACHE_DIR` and refuses repo-local cache roots.
Cache keys remain stable for identical normalized requests and rates.

Runtime logs and operator receipt files use `TTS_LOG_DIR`. The log root must be outside the repo in
operator deployments, or a test temporary directory in CI. CI must not require a real `/Volumes`
mount or model files.

## UI Boundary

The Companion UI dev server proxies TTS calls through same-origin routes. Browser clients do not
need direct access to the runtime API port.

Read-back buttons may request planning and synthesis only after a human action. The UI must not
autoplay on page load and must not route read-back through mutation endpoints such as note save,
Panel confirmation, or workspace update.

The read-back UI inspects the `SpeechPlan` before synthesis and renders normalized readable text,
segment locale, provider, voice, cache status, and warnings. It surfaces uncertain mixed-language
plans, skipped code blocks, and missing provider/model warnings before playback. Browser/system
speech synthesis remains outside the default path.
