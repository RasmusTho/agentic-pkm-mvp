"""Qualified TEST-channel sv/en acceptance for ``POST /api/ask/voice`` (#6234).

One bounded technical-acceptance verifier for the Mimer voice loop. It sends one
synthetic Swedish and one synthetic English audio question through the actual
configured ASR -> grounded ASK -> TTS routes of an already qualified TEST
Product channel and emits a compact, secret-free
``voice_test_channel_acceptance.v1`` receipt for the parent validation Issue.

Boundaries (fail closed):

* The run binds to one exact qualified candidate (source SHA + image digest)
  and to accepted route/instance qualification evidence supplied in a
  ``voice_test_channel_qualification.v1`` input. The observed ``/version`` and
  ``/api/health`` identity must match before and after the voice turns.
* Only the ``test`` channel is admitted. A PROD target, an unqualified route,
  a mismatched candidate or an unavailable endpoint is refused before any voice
  turn is sent.
* The transport admits only read-only identity GETs, the derived TTS audio GET
  and the voice POST itself. The voice turn's only durable effect is the
  already-authorized append-only voice-session transcript for the synthetic
  actor; each turn closes its session. Nothing here deploys, configures,
  grants access, or touches credentials.
* The receipt never contains audio bytes, prompts, transcript/answer text or
  credential values. An optional bearer token is read from the environment
  variable named by ``AUTH_TOKEN_ENV`` and is never recorded.
* The qualification evidence (refs, receipt hashes, status, routes) is an
  operator-supplied input; it is validated for shape and candidate agreement and
  reported verbatim so the parent reviewer can check it against the referenced
  receipts. Public ``/api/health`` deliberately neutralizes LLM route identity,
  and the topology carries no ingress host, so those bindings are not re-observed.
* ``/api/ask/voice`` has no actor or route-identity field. The synthetic actor
  is therefore a reference to the TEST channel's qualified synthetic actor and
  source binding, and the ASR/ASK route identities and image digest are bound
  through the qualification evidence and the fresh TEST
  ``product_tars_channel_topology.v1`` observation; the TTS provider/voice per
  segment and the running git SHA are observed directly.

Run (operator/coordinator, after #5977 and #6190 qualification evidence)::

    python -m app.ops.voice_test_channel_acceptance \
        --qualification /private/path/voice-qualification.json \
        --out /private/path/voice-receipt.json
"""

from __future__ import annotations

import argparse
from array import array
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid
import wave

from app.ops.product_tars_channel_topology import (
    ProductTarsChannelTopologyError,
    load_and_validate_product_tars_channel_topology,
)

QUALIFICATION_SCHEMA = "voice_test_channel_qualification.v1"
RECEIPT_SCHEMA = "voice_test_channel_acceptance.v1"
LANGUAGES = ("sv", "en")
CHANNEL = "test"
AUTH_TOKEN_ENV = "VOICE_ACCEPTANCE_BEARER_TOKEN"
VOICE_PATH = "/api/ask/voice"
VERSION_PATH = "/version"
HEALTH_PATH = "/api/health"
AUDIO_PATH = re.compile(r"/api/companion/tts/audio/([a-f0-9]{64})\.wav")
ALLOWED_GET = frozenset({VERSION_PATH, HEALTH_PATH})
ALLOWED_POST = frozenset({VOICE_PATH})
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_FIXTURE_BYTES = 8 * 1024 * 1024
DEGRADED_REASONS = frozenset({"tts_unavailable", "capture_intent_surfaced"})
# The voice-session transcript is best effort (INV-VOICE-A); its absence is
# reported in the receipt but does not negate an audible grounded answer.
TRANSCRIPT_BEST_EFFORT = "session_transcript_unavailable"
AUDIBLE_PEAK_FRACTION = 0.01
_PCM_CODES = {1: "B", 2: "h", 4: "i"}
_PROD_HOST_TOKENS = frozenset({"prod", "production", "prd", "stable"})

_SHA = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_ACTOR = re.compile(r"synthetic-[a-z0-9][a-z0-9-]{2,62}")
_ISSUE_REF = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[0-9]+")
_SENSITIVE_KEY = re.compile(
    r"(?:password|token|credential|private[_-]?key|api[_-]?key|secret|authorization|dsn|cookie)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?:bearer\s+\S|\bgh[pousr]_|\bsk-[A-Za-z0-9]|[A-Za-z][A-Za-z0-9+.-]*://[^\s/@]+@|"
    r"(?:password|passwd|secret|token|api[_-]?key)\s*=\s*\S)",
    re.IGNORECASE,
)


class VoiceAcceptanceRefusal(Exception):
    """A fail-closed refusal; ``reason`` is a stable, secret-free code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Transport(Protocol):
    def get(self, path: str, query: Mapping[str, str] | None = None) -> tuple[int, str, bytes]: ...

    def post_voice(self, audio: bytes, content_type: str, fields: Mapping[str, str]) -> tuple[int, str, bytes]: ...


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise VoiceAcceptanceRefusal(reason)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash_json(value: Any) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _walk_secret_free(value: Any, *, reason: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            _require(not _SENSITIVE_KEY.search(str(key)), reason)
            _walk_secret_free(child, reason=reason)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _walk_secret_free(child, reason=reason)
    elif isinstance(value, (bytes, bytearray)):
        raise VoiceAcceptanceRefusal(reason)
    elif isinstance(value, str):
        _require(not _SENSITIVE_VALUE.search(value), reason)


def _origin(api_url: str) -> str:
    parsed = urlparse(api_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def validate_qualification(payload: Any, *, base_dir: Path | None = None) -> dict[str, Any]:
    """Validate one qualification input; no network or file effect besides reads."""

    _require(isinstance(payload, Mapping), "qualification_invalid")
    _walk_secret_free(payload, reason="qualification_contains_secret")
    expected = {"schema", "channel", "api_url", "candidate", "qualification", "routes",
                "synthetic_actor", "fixtures", "deployment_topology_path"}
    _require(set(payload) - {"scope"} == expected, "qualification_fields_invalid")
    _require(payload["schema"] == QUALIFICATION_SCHEMA, "qualification_schema_invalid")
    channel = str(payload["channel"]).strip().lower()
    _require(channel != "prod", "prod_target_refused")
    _require(channel == CHANNEL, "channel_not_test")

    api_url = payload["api_url"]
    _require(isinstance(api_url, str), "api_url_invalid")
    parsed = urlparse(api_url)
    _require(parsed.scheme in {"http", "https"} and bool(parsed.hostname), "api_url_invalid")
    _require(not (parsed.username or parsed.password or parsed.query or parsed.fragment), "api_url_invalid")
    _require(parsed.path in {"", "/"}, "api_url_invalid")
    host_tokens = set(re.split(r"[^a-z0-9]+", (parsed.hostname or "").lower()))
    _require(host_tokens.isdisjoint(_PROD_HOST_TOKENS), "prod_target_refused")

    candidate = payload["candidate"]
    _require(isinstance(candidate, Mapping) and set(candidate) == {"source_sha", "image_digest"},
             "candidate_identity_invalid")
    _require(isinstance(candidate["source_sha"], str) and bool(_SHA.fullmatch(candidate["source_sha"])),
             "candidate_identity_invalid")
    _require(isinstance(candidate["image_digest"], str) and bool(_DIGEST.fullmatch(candidate["image_digest"])),
             "candidate_identity_invalid")

    qualification = payload["qualification"]
    _require(isinstance(qualification, Mapping) and set(qualification) == {"route", "instance"},
             "qualification_evidence_invalid")
    for item in qualification.values():
        _require(isinstance(item, Mapping) and set(item) == {"ref", "receipt_sha256", "status",
                                                            "source_sha", "image_digest", "channel"},
                 "qualification_evidence_invalid")
        _require(isinstance(item["ref"], str) and bool(_ISSUE_REF.fullmatch(item["ref"])),
                 "qualification_evidence_invalid")
        _require(isinstance(item["receipt_sha256"], str) and bool(_HEX64.fullmatch(item["receipt_sha256"])),
                 "qualification_evidence_invalid")
        _require(item["status"] == "qualified", "route_or_instance_unqualified")
        _require(str(item["channel"]).strip().lower() == CHANNEL, "qualification_channel_mismatch")
        _require(item["source_sha"] == candidate["source_sha"] and item["image_digest"] == candidate["image_digest"],
                 "qualification_candidate_mismatch")

    routes = payload["routes"]
    _require(isinstance(routes, Mapping) and set(routes) == {"asr", "ask", "tts"}, "routes_invalid")
    for name in ("asr", "ask"):
        route = routes[name]
        _require(isinstance(route, Mapping) and set(route) == {"provider", "model"}
                 and all(isinstance(v, str) and v and v != "unknown" for v in route.values()), "routes_invalid")
    tts = routes["tts"]
    _require(isinstance(tts, Mapping) and set(tts) == set(LANGUAGES), "routes_invalid")
    for route in tts.values():
        _require(isinstance(route, Mapping) and set(route) == {"provider", "voice_id"}
                 and all(isinstance(v, str) and v and v != "unknown" for v in route.values()), "routes_invalid")

    actor = payload["synthetic_actor"]
    _require(isinstance(actor, str) and bool(_ACTOR.fullmatch(actor)), "synthetic_actor_invalid")
    scope = payload.get("scope")
    _require(scope is None or (isinstance(scope, str) and 0 < len(scope) <= 128), "scope_invalid")

    fixtures = payload["fixtures"]
    _require(isinstance(fixtures, Mapping) and set(fixtures) == set(LANGUAGES), "fixtures_invalid")
    resolved: dict[str, dict[str, Any]] = {}
    for language, fixture in fixtures.items():
        _require(isinstance(fixture, Mapping) and set(fixture) == {"audio_path", "audio_sha256",
                                                                  "expected_source_ids"}, "fixtures_invalid")
        _require(isinstance(fixture["audio_sha256"], str) and bool(_HEX64.fullmatch(fixture["audio_sha256"])),
                 "fixtures_invalid")
        ids = fixture["expected_source_ids"]
        _require(isinstance(ids, list) and 1 <= len(ids) <= 32
                 and all(isinstance(x, str) and x for x in ids), "fixtures_invalid")
        path = Path(str(fixture["audio_path"]))
        if not path.is_absolute():
            if base_dir is None:
                raise VoiceAcceptanceRefusal("fixtures_invalid")
            path = base_dir / path
        resolved[language] = {"audio_path": path, "audio_sha256": fixture["audio_sha256"],
                              "expected_source_ids": list(ids)}
    result = dict(payload)
    result["input_sha256"] = _hash_json(payload)
    result["channel"] = channel
    result["api_url"] = _origin(api_url)
    result["fixtures"] = resolved
    topology_path = Path(str(payload["deployment_topology_path"]))
    if not topology_path.is_absolute():
        if base_dir is None:
            raise VoiceAcceptanceRefusal("deployment_identity_unavailable")
        topology_path = base_dir / topology_path
    result["deployment"] = deployment_identity(topology_path, candidate)
    del result["deployment_topology_path"]
    return result


def deployment_identity(path: Path, candidate: Mapping[str, str]) -> dict[str, str]:
    """Bind the image digest through the existing redaction-safe TARS topology input.

    The Product ``/version`` surface exposes only the git SHA, so the running
    image identity comes from the fresh (<=24h) ``product_tars_channel_topology.v1``
    observation for the TEST channel; it must name exactly the qualified digest.
    """

    try:
        topology = load_and_validate_product_tars_channel_topology(path)
    except ProductTarsChannelTopologyError as exc:
        raise VoiceAcceptanceRefusal("deployment_identity_unavailable") from exc
    entry = next(x for x in topology["channels"] if x["channel"] == CHANNEL)
    _require(not entry["refusals"], "deployment_identity_refused")
    image = entry["source_image_identity"]
    _require(image != "unknown" and image.endswith("@" + candidate["image_digest"]), "deployment_image_mismatch")
    version = entry["health_version"].removeprefix("version:").lower()
    _require(bool(re.fullmatch(r"[0-9a-f]{7,40}", version)), "deployment_identity_unverified")
    _require(candidate["source_sha"].startswith(version), "deployment_image_mismatch")
    return {"source_ref": topology["source_ref"], "observed_at": topology["observed_at"],
            "source_image_identity": image, "topology_sha256": _hash_json(topology)}


def _json(status: int, raw: bytes, reason: str) -> dict[str, Any]:
    _require(status == 200, reason)
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise VoiceAcceptanceRefusal(reason) from exc
    _require(isinstance(value, dict), reason)
    return value


def observe_candidate(q: Mapping[str, Any], transport: Transport) -> dict[str, Any]:
    """Read the running identity; refuse PROD, a foreign channel or another candidate."""

    try:
        status, _, raw = transport.get(VERSION_PATH)
        version = _json(status, raw, "target_unavailable")
        status, _, raw = transport.get(HEALTH_PATH, {"model_access_sampling": "cache"})
        health = _json(status, raw, "target_unavailable")
    except VoiceAcceptanceRefusal:
        raise
    except Exception as exc:
        raise VoiceAcceptanceRefusal("target_unavailable") from exc
    environment = str(health.get("environment") or "").strip().lower()
    _require(environment != "prod", "prod_target_refused")
    _require(environment == CHANNEL, "channel_mismatch")
    running = str(version.get("git_sha") or "").strip().lower()
    _require(running == q["candidate"]["source_sha"], "candidate_mismatch")
    health_sha = str(health.get("version") or "").strip().lower()
    _require(health_sha == running, "candidate_mismatch")
    # The Product /version surface exposes only the git SHA today. A digest is
    # compared whenever the target reports one; otherwise the digest is bound by
    # the fresh TEST channel topology observation validated with the input.
    digest = version.get("image_digest")
    if digest is not None:
        _require(str(digest).strip().lower() == q["candidate"]["image_digest"], "candidate_mismatch")
    return {"channel": environment, "source_sha": running, "health_ok": health.get("ok") is True,
            "image_digest_source": "observed" if digest is not None else "channel_topology"}


def _read_fixture(fixture: Mapping[str, Any]) -> bytes:
    path = Path(fixture["audio_path"])
    try:
        _require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_FIXTURE_BYTES,
                 "fixture_unavailable")
        raw = path.read_bytes()
    except OSError as exc:
        raise VoiceAcceptanceRefusal("fixture_unavailable") from exc
    _require(_sha256(raw) == fixture["audio_sha256"], "fixture_hash_mismatch")
    _require(raw.startswith(b"RIFF") and raw[8:12] == b"WAVE", "fixture_not_wav")
    return raw


def _audio_metadata(raw: bytes) -> dict[str, Any]:
    try:
        with wave.open(io.BytesIO(raw)) as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            pcm = audio.readframes(frames)
            compressed = audio.getcomptype() != "NONE"
            width = audio.getsampwidth()
            channels = audio.getnchannels()
    except (EOFError, wave.Error) as exc:
        raise AssertionError("audio_not_decodable_wav") from exc
    if frames <= 0 or rate <= 0 or compressed or not pcm:
        raise AssertionError("audio_empty_or_silent")
    if len(pcm) != frames * width * channels:
        raise AssertionError("audio_truncated")
    if width not in _PCM_CODES:
        raise AssertionError("audio_sample_width_unsupported")
    samples = array(_PCM_CODES[width])
    samples.frombytes(pcm[: len(pcm) - len(pcm) % width])
    centre, full_scale = (128, 128) if width == 1 else (0, 2 ** (8 * width - 1))
    threshold = full_scale * AUDIBLE_PEAK_FRACTION
    audible = sum(1 for x in samples if abs(x - centre) >= threshold)
    if audible < max(10, len(samples) // 1000):
        raise AssertionError("audio_empty_or_silent")
    return {"format": "audio/wav", "sha256": _sha256(raw), "bytes": len(raw), "frames": frames,
            "sample_rate": rate, "duration_ms": int(frames * 1000 / rate)}


def _safe(value: Any) -> str | None:
    """A server-supplied identifier, hashed if it resembles secret material."""

    if value is None or value == "":
        return None
    text = str(value)[:512]
    return "sha256:" + _sha256(text.encode()) if _SENSITIVE_VALUE.search(text) else text


def _citations(sources: Any) -> list[dict[str, str | None]]:
    if not isinstance(sources, list):
        return []
    return [{"uuid": _safe(s.get("uuid")), "path": _safe(s.get("path"))} for s in sources if isinstance(s, Mapping)]


def verify_language(q: Mapping[str, Any], language: str, transport: Transport) -> dict[str, Any]:
    """One synthetic voice turn. Returns a secret-free outcome; never raises AssertionError."""

    fixture = q["fixtures"][language]
    route = q["routes"]["tts"][language]
    outcome: dict[str, Any] = {"status": "failed", "reason": None, "fixture_sha256": fixture["audio_sha256"]}
    try:
        audio = _read_fixture(fixture)
        fields = {"end_session": "true"}
        if q.get("scope"):
            fields["scope"] = q["scope"]
        status, _, raw = transport.post_voice(audio, "audio/wav", fields)
        if status != 200:
            raise AssertionError(f"voice_http_{int(status)}")
        try:
            body = json.loads(raw)
        except ValueError as exc:
            raise AssertionError("voice_response_invalid") from exc
        if not isinstance(body, dict):
            raise AssertionError("voice_response_invalid")
        outcome["trace_id"] = _safe(body.get("trace_id"))
        detected = str(body.get("detected_language") or "").lower()[:16]
        outcome["detected_language"] = _safe(detected)
        outcome["transcript_present"] = bool(str(body.get("transcript") or "").strip())
        outcome["answer_present"] = bool(str(body.get("answer") or "").strip())
        citations = _citations(body.get("sources"))
        outcome["citations"] = citations
        session_error = body.get("session_error")
        outcome["session_transcript"] = "unavailable" if session_error else "recorded"
        if not outcome["transcript_present"]:
            raise AssertionError("transcript_missing")
        if not detected.startswith(language):
            raise AssertionError("detected_language_mismatch")
        if body.get("reason") in DEGRADED_REASONS or (
            body.get("degraded") is True and body.get("reason") != TRANSCRIPT_BEST_EFFORT
        ):
            raise AssertionError("voice_degraded_" + re.sub(r"[^a-z0-9_]", "", str(body.get("reason") or "unknown"))[:48])
        if not outcome["answer_present"]:
            raise AssertionError("answer_missing")
        expected = set(fixture["expected_source_ids"])
        raw_ids = [str(s.get(k)) for s in (body.get("sources") or []) if isinstance(s, Mapping)
                   for k in ("uuid", "path") if s.get(k)]
        matched = sorted({_safe(v) or "" for v in raw_ids if v in expected})
        outcome["expected_citations_matched"] = matched
        if not citations:
            raise AssertionError("grounded_citation_missing")
        if not matched:
            raise AssertionError("citation_not_from_synthetic_source")
        plan = body.get("speech_plan")
        if not isinstance(plan, dict):
            raise AssertionError("speech_plan_missing")
        raw_segments = plan.get("segments")
        segments: list[Any] = raw_segments if isinstance(raw_segments, list) else []
        outcome["tts"] = {"provider": _safe(plan.get("provider")), "voice_id": _safe(plan.get("voice_id")),
                          "segments": [{k: _safe(s.get(k)) for k in ("language", "provider", "voice_id")}
                                       for s in segments if isinstance(s, dict)]}
        if (plan.get("enabled") is not True or plan.get("local_only") is not True
                or plan.get("allow_cloud_fallback") is not False or plan.get("allow_browser_fallback") is not False):
            raise AssertionError("tts_route_not_local_qualified")
        # Each sentence segment must use the qualified voice for its own language
        # (a mixed sv/en answer is legitimate); the plan voice is the turn's language.
        def qualified(segment: Any) -> bool:
            if not isinstance(segment, dict) or segment.get("provider_available") is not True:
                return False
            seg_language = str(segment.get("language") or "")[:2].lower()
            seg_route = q["routes"]["tts"].get(seg_language)
            return bool(seg_route) and all(segment.get(k) == seg_route[k] for k in ("provider", "voice_id"))

        if (not segments or not all(qualified(s) for s in segments)
                or plan.get("provider") != route["provider"] or plan.get("voice_id") != route["voice_id"]):
            raise AssertionError("tts_route_mismatch")
        audio_url = str(body.get("audio_url") or "")
        match = AUDIO_PATH.fullmatch(audio_url)
        if match is None or audio_url != plan.get("audio_url") or match.group(1) != plan.get("cache_key"):
            raise AssertionError("audio_unavailable")
        audio_status, content_type, audio_raw = transport.get(audio_url)
        if audio_status != 200 or not content_type.lower().startswith("audio/wav"):
            raise AssertionError("audio_unavailable")
        outcome["audio"] = _audio_metadata(audio_raw)
        outcome["status"] = "passed"
    except VoiceAcceptanceRefusal as exc:
        outcome["reason"] = exc.reason
    except AssertionError as exc:
        outcome["reason"] = str(exc)
    except Exception:  # transport/network failure is a failed language, not a pass
        outcome["reason"] = "voice_turn_unavailable"
    return outcome


def _base_receipt(q: Mapping[str, Any] | None) -> dict[str, Any]:
    module = Path(__file__)
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "run_id": str(uuid.uuid4()),
        "started_at": datetime.now(UTC).isoformat(),
        "verifier": {"module": "app.ops.voice_test_channel_acceptance", "sha256": _sha256(module.read_bytes())},
        "channel": CHANNEL,
        "passed": False,
        "outcome": "refused",
        "refusal": None,
        "languages": {language: {"status": "not_run", "reason": None} for language in LANGUAGES},
    }
    if q is not None:
        receipt.update(
            target_origin=q["api_url"],
            candidate=dict(q["candidate"]),
            qualification={k: {x: v[x] for x in ("ref", "receipt_sha256", "status")}
                           for k, v in q["qualification"].items()},
            routes=json.loads(json.dumps(q["routes"])),
            synthetic_actor=q["synthetic_actor"],
            scope_bound=bool(q.get("scope")),
            deployment=dict(q["deployment"]),
            # Recomputable: sha256 of the input JSON with sorted keys and compact separators.
            qualification_sha256=q["input_sha256"],
        )
    return receipt


def assert_receipt_secret_free(receipt: Mapping[str, Any]) -> None:
    _walk_secret_free(receipt, reason="receipt_contains_secret")
    forbidden = {"transcript", "answer", "audio_bytes", "prompt", "question", "text", "normalized_text"}

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                _require(key not in forbidden, "receipt_contains_content")
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(receipt)


def run_acceptance(payload: Any, transport: Transport, *, base_dir: Path | None = None) -> dict[str, Any]:
    """Run both languages against one qualified TEST candidate; always returns a receipt."""

    q: dict[str, Any] | None = None
    try:
        q = validate_qualification(payload, base_dir=base_dir)
    except VoiceAcceptanceRefusal as exc:
        receipt = _base_receipt(None)
        receipt["refusal"] = exc.reason
        return _finish(receipt)
    receipt = _base_receipt(q)
    try:
        receipt["observed_before"] = observe_candidate(q, transport)
    except VoiceAcceptanceRefusal as exc:
        receipt["refusal"] = exc.reason  # refused before any voice turn
        return _finish(receipt)
    for language in LANGUAGES:
        receipt["languages"][language] = verify_language(q, language, transport)
    try:
        receipt["observed_after"] = observe_candidate(q, transport)
    except VoiceAcceptanceRefusal as exc:
        # Voice turns already ran: this is a failed run, never a pre-turn refusal.
        receipt["outcome"] = "failed"
        receipt["refusal"] = "candidate_drift" if exc.reason == "candidate_mismatch" else "post_run_" + exc.reason
        return _finish(receipt)
    receipt["passed"] = all(receipt["languages"][x]["status"] == "passed" for x in LANGUAGES)
    receipt["outcome"] = "passed" if receipt["passed"] else "failed"
    return _finish(receipt)


def _finish(receipt: dict[str, Any]) -> dict[str, Any]:
    receipt["finished_at"] = datetime.now(UTC).isoformat()
    try:
        assert_receipt_secret_free(receipt)
    except VoiceAcceptanceRefusal as exc:
        # Never emit, and never crash on, a receipt that fails the secret scan.
        return {"schema": RECEIPT_SCHEMA, "run_id": receipt["run_id"], "channel": CHANNEL,
                "passed": False, "outcome": "failed", "refusal": exc.reason,
                "started_at": receipt["started_at"], "finished_at": receipt["finished_at"],
                "languages": {x: {"status": receipt["languages"][x]["status"], "reason": None}
                              for x in LANGUAGES}}
    return receipt


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise VoiceAcceptanceRefusal("target_redirect_refused")


class HttpTransport:
    """Allowlisted HTTP to one origin: identity/audio GETs and the voice POST only."""

    def __init__(self, origin: str, *, token: str | None = None, timeout: float = 120.0,
                 opener: Callable[..., Any] | None = None) -> None:
        self._origin = origin.rstrip("/")
        _require(not token or urlparse(self._origin).scheme == "https", "bearer_requires_https")
        self._token = token
        self._timeout = timeout
        # An empty ProxyHandler keeps the request (and any bearer) off HTTP(S)_PROXY.
        self._open = opener or build_opener(ProxyHandler({}), _NoRedirect()).open

    def _send(self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None,
              query: Mapping[str, str] | None = None) -> tuple[int, str, bytes]:
        if method == "GET":
            _require(path in ALLOWED_GET or AUDIO_PATH.fullmatch(path) is not None, "transport_path_refused")
        else:
            _require(method == "POST" and path in ALLOWED_POST, "transport_path_refused")
        url = self._origin + path + ("?" + urlencode(dict(query)) if query else "")
        request = Request(url, data=body, method=method, headers=dict(headers or {}))
        if self._token:
            request.add_header("Authorization", "Bearer " + self._token)
        try:
            with self._open(request, timeout=self._timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                status, content_type = response.status, response.headers.get("content-type", "")
        except HTTPError as exc:
            raw, status, content_type = exc.read(MAX_RESPONSE_BYTES + 1), exc.code, exc.headers.get("content-type", "")
        except URLError as exc:
            raise VoiceAcceptanceRefusal("target_unavailable") from exc
        _require(len(raw) <= MAX_RESPONSE_BYTES, "target_response_unbounded")
        return status, content_type, raw

    def get(self, path: str, query: Mapping[str, str] | None = None) -> tuple[int, str, bytes]:
        return self._send("GET", path, query=query)

    def post_voice(self, audio: bytes, content_type: str, fields: Mapping[str, str]) -> tuple[int, str, bytes]:
        boundary = "voiceacceptance" + uuid.uuid4().hex
        parts = [
            (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode()
            for name, value in fields.items()
        ]
        parts.append(
            (f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="question.wav"\r\n'
             f"Content-Type: {content_type}\r\n\r\n").encode() + audio + b"\r\n"
        )
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        return self._send("POST", VOICE_PATH, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--qualification", type=Path, required=True,
                        help=f"{QUALIFICATION_SCHEMA} JSON (private file)")
    parser.add_argument("--out", type=Path, help="write the receipt here (refuses to overwrite)")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.qualification.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    origin = _origin(payload["api_url"]) if isinstance(payload, dict) and isinstance(payload.get("api_url"), str) else ""
    # Reserve the receipt path before any voice turn so a collision cannot discard
    # evidence of turns that already ran (and tempt a replay).
    out = None
    if args.out is not None:
        out = os.fdopen(os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8")
    try:
        try:
            transport = HttpTransport(origin, token=os.environ.get(AUTH_TOKEN_ENV) or None)
            receipt = run_acceptance(payload, transport, base_dir=args.qualification.resolve().parent)
        except VoiceAcceptanceRefusal as exc:
            receipt = _finish({**_base_receipt(None), "refusal": exc.reason})
        except Exception as exc:  # never leave an empty receipt behind
            receipt = _finish({**_base_receipt(None), "outcome": "failed",
                               "refusal": "verifier_error_" + type(exc).__name__})
        text = json.dumps(receipt, indent=2, sort_keys=True)
        if out is not None:
            out.write(text + "\n")
    finally:
        if out is not None:
            out.close()
    print(text)
    return 0 if receipt["passed"] else (2 if receipt["outcome"] == "refused" else 1)


if __name__ == "__main__":
    sys.exit(main())
