"""Deterministic contract tests for the qualified TEST voice acceptance verifier (#6234).

HTTP is a double here; these tests prove binding, refusal and receipt shape.
The live sv/en run against the qualified TEST channel is the parent's receipt.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import struct
from typing import Any, Mapping
import wave

import pytest

from app.ops import voice_test_channel_acceptance as vta

SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64
ROUTES = {
    "asr": {"provider": "faster-whisper", "model": "base"},
    "ask": {"provider": "product-gateway", "model": "qualified-ask-route"},
    "tts": {"sv": {"provider": "piper", "voice_id": "sv_SE-lisa-medium"},
            "en": {"provider": "kokoro", "voice_id": "bf_isabella"}},
}
SOURCES = {"sv": "synthetic/voice/sv-source.md", "en": "synthetic/voice/en-source.md"}
TRANSCRIPTS = {"sv": "Vad står det i den syntetiska anteckningen?", "en": "What does the synthetic note say?"}
ANSWER = "The synthetic note describes the harbour schedule."
TOKEN = "s3cr3t-bearer-value"


def _wav(seconds: float = 0.2, *, silent: bool = False, amplitude: int = 100) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        frames = int(16000 * seconds)
        out.writeframes(b"".join(struct.pack("<h", 0 if silent else ((i % 200) - 100) * amplitude) for i in range(frames)))
    return buffer.getvalue()


FIXTURE_AUDIO = {"sv": _wav(0.3), "en": _wav(0.25)}
REPLY_AUDIO = _wav(0.5)


def _topology(*, digest: str = DIGEST, age: timedelta = timedelta(minutes=5),
              refusals: list[str] | None = None) -> dict[str, Any]:
    def entry(channel: str) -> dict[str, Any]:
        return {"channel": channel, "vm_identity": f"tars-vm:ygg-{channel}",
                "engine_identity": f"docker-engine:ygg-{channel}",
                "source_image_identity": "image:ghcr.io/example/pkm@" + (digest if channel == "test" else DIGEST),
                "ingress_auth_class": "private-tailscale", "health_version": "version:" + SHA[:12],
                "data_backup_rollback_boundary": "explicit-gap", "gaps": ["backup_unqualified"],
                "refusals": (refusals or []) if channel == "test" else []}

    return {"schema_version": "product_tars_channel_topology.v1",
            "observed_at": (datetime.now(UTC) - age).isoformat(), "source_ref": "qualification:voice-6234",
            "channels": [entry(x) for x in ("dev", "test", "prod")]}


def _qualification(tmp_path: Path, *, topology: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "topology.json").write_text(json.dumps(topology or _topology()))
    fixtures = {}
    for language, raw in FIXTURE_AUDIO.items():
        (tmp_path / f"{language}.wav").write_bytes(raw)
        fixtures[language] = {"audio_path": f"{language}.wav", "audio_sha256": hashlib.sha256(raw).hexdigest(),
                              "expected_source_ids": [SOURCES[language]]}
    evidence = {"status": "qualified", "source_sha": SHA, "image_digest": DIGEST, "channel": "test"}
    payload = {
        "schema": vta.QUALIFICATION_SCHEMA,
        "channel": "test",
        "api_url": "https://ygg-test.example.internal",
        "candidate": {"source_sha": SHA, "image_digest": DIGEST},
        "qualification": {
            "route": {"ref": "RasmusTho/agentic-pkm-mvp#5977", "receipt_sha256": "c" * 64, **evidence},
            "instance": {"ref": "RasmusTho/agentic-pkm-mvp#6190", "receipt_sha256": "d" * 64, **evidence},
        },
        "routes": json.loads(json.dumps(ROUTES)),
        "synthetic_actor": "synthetic-voice-acceptance-v1",
        "fixtures": fixtures,
        "deployment_topology_path": "topology.json",
    }
    payload.update(overrides)
    return payload


class FakeTestChannel:
    """Simulates the qualified TEST API surface; records every request."""

    def __init__(self, *, environment: str = "test", git_sha: str = SHA, available: bool = True) -> None:
        self.environment = environment
        self.git_sha = git_sha
        self.available = available
        self.calls: list[tuple[str, str]] = []
        self.voice_turns: list[Mapping[str, str]] = []
        self.drift_after_voice = False
        self.tts_override: dict[str, Any] = {}
        self.sources_override: list[dict[str, Any]] | None = None
        self.body_override: dict[str, Any] = {}
        self.health_override: dict[str, Any] = {}

    def get(self, path: str, query: Mapping[str, str] | None = None) -> tuple[int, str, bytes]:
        self.calls.append(("GET", path))
        if not self.available:
            raise ConnectionError("unreachable")
        if path == "/version":
            sha = "e" * 40 if self.drift_after_voice and self.voice_turns else self.git_sha
            return 200, "application/json", json.dumps({"git_sha": sha, "built_at": ""}).encode()
        if path == "/api/health":
            assert query == {"model_access_sampling": "cache"}
            health = {"environment": self.environment, "ok": True, "version": self.git_sha, **self.health_override}
            return 200, "application/json", json.dumps({k: v for k, v in health.items() if v is not None}).encode()
        if vta.AUDIO_PATH.fullmatch(path):
            return 200, "audio/wav", REPLY_AUDIO
        return 404, "application/json", b"{}"

    def post_voice(self, audio: bytes, content_type: str, fields: Mapping[str, str]) -> tuple[int, str, bytes]:
        self.calls.append(("POST", "/api/ask/voice"))
        self.voice_turns.append(dict(fields))
        language = next(x for x, raw in FIXTURE_AUDIO.items() if raw == audio)
        route = {**ROUTES["tts"][language], **self.tts_override}
        key = hashlib.sha256(audio).hexdigest()
        url = f"/api/companion/tts/audio/{key}.wav"
        sources = self.sources_override if self.sources_override is not None else [
            {"uuid": "11111111-2222-3333-4444-555555555555", "path": SOURCES[language], "title": "Synthetic"}]
        body = {
            "transcript": TRANSCRIPTS[language], "detected_language": language, "answer": ANSWER,
            "sources": sources, "audio_url": url, "session_id": "voice-1", "session_error": None,
            "trace_id": f"trace-{language}", "degraded": False, "reason": None,
            "speech_plan": {"enabled": True, "local_only": True, "allow_cloud_fallback": False,
                            "allow_browser_fallback": False, "normalized_text": ANSWER, "cache_key": key,
                            "audio_url": url, "provider_available": True, **route,
                            "segments": [{"index": 0, "language": language, "text": ANSWER,
                                          "provider_available": True, **route}]},
        }
        body.update(self.body_override)
        return 200, "application/json", json.dumps(body).encode()


def _run(tmp_path: Path, target: FakeTestChannel, **overrides: Any) -> dict[str, Any]:
    return vta.run_acceptance(_qualification(tmp_path, **overrides), target, base_dir=tmp_path)


def test_swedish_and_english_use_qualified_routes_and_return_audio(tmp_path: Path) -> None:
    channel = FakeTestChannel()
    receipt = _run(tmp_path, channel)

    assert receipt["passed"] is True and receipt["outcome"] == "passed" and receipt["refusal"] is None
    assert [c for c in channel.calls if c[0] == "POST"] == [("POST", "/api/ask/voice")] * 2
    assert all(turn["end_session"] == "true" for turn in channel.voice_turns)
    for language in ("sv", "en"):
        outcome = receipt["languages"][language]
        assert outcome["status"] == "passed"
        assert outcome["detected_language"] == language and outcome["transcript_present"] is True
        assert outcome["expected_citations_matched"] == [SOURCES[language]]
        assert outcome["tts"]["provider"] == ROUTES["tts"][language]["provider"]
        assert outcome["tts"]["voice_id"] == ROUTES["tts"][language]["voice_id"]
        assert outcome["audio"]["sha256"] == hashlib.sha256(REPLY_AUDIO).hexdigest()
        assert outcome["audio"]["frames"] > 0 and outcome["audio"]["format"] == "audio/wav"

    # A SpeechPlan alone is not audible success: route drift, missing citation,
    # silent or missing audio each fail that language.
    drift = FakeTestChannel()
    drift.tts_override = {"provider": "browser", "voice_id": "fallback"}
    assert _run(tmp_path / "d", drift)["languages"]["sv"]["reason"] == "tts_route_mismatch"

    uncited = FakeTestChannel()
    uncited.sources_override = []
    result = _run(tmp_path / "u", uncited)
    assert result["passed"] is False and result["languages"]["en"]["reason"] == "grounded_citation_missing"

    foreign = FakeTestChannel()
    foreign.sources_override = [{"uuid": "x", "path": "private/real-note.md"}]
    assert _run(tmp_path / "f", foreign)["languages"]["sv"]["reason"] == "citation_not_from_synthetic_source"

    # Any degraded turn fails, except the documented best-effort transcript marker.
    degraded = FakeTestChannel()
    degraded.body_override = {"degraded": True, "reason": "retrieval_partial"}
    assert _run(tmp_path / "g", degraded)["languages"]["sv"]["reason"] == "voice_degraded_retrieval_partial"
    unlogged = FakeTestChannel()
    unlogged.body_override = {"degraded": True, "reason": "session_transcript_unavailable",
                              "session_error": "session_transcript_unavailable"}
    unlogged_receipt = _run(tmp_path / "l", unlogged)
    assert unlogged_receipt["passed"] is True
    assert unlogged_receipt["languages"]["en"]["session_transcript"] == "unavailable"

    class Silent(FakeTestChannel):
        def get(self, path: str, query: Mapping[str, str] | None = None) -> tuple[int, str, bytes]:
            if vta.AUDIO_PATH.fullmatch(path):
                return 200, "audio/wav", _wav(silent=True)
            return super().get(path, query)

    assert _run(tmp_path / "s", Silent())["languages"]["en"]["reason"] == "audio_empty_or_silent"

    class NearSilent(FakeTestChannel):
        def get(self, path: str, query: Mapping[str, str] | None = None) -> tuple[int, str, bytes]:
            if vta.AUDIO_PATH.fullmatch(path):
                return 200, "audio/wav", _wav(amplitude=1)
            return super().get(path, query)

    assert _run(tmp_path / "n", NearSilent())["languages"]["sv"]["reason"] == "audio_empty_or_silent"

    class Truncated(FakeTestChannel):
        def get(self, path: str, query: Mapping[str, str] | None = None) -> tuple[int, str, bytes]:
            if vta.AUDIO_PATH.fullmatch(path):
                return 200, "audio/wav", REPLY_AUDIO[:-2000]
            return super().get(path, query)

    assert _run(tmp_path / "t", Truncated())["languages"]["en"]["reason"] == "audio_truncated"


@pytest.mark.parametrize(
    ("override", "channel_kwargs", "reason"),
    [
        ({"channel": "prod"}, {}, "prod_target_refused"),
        ({"api_url": "https://ygg-prod.example.internal"}, {}, "prod_target_refused"),
        ({"api_url": "https://ygg-production.example.internal"}, {}, "prod_target_refused"),
        ({"api_url": "https://stable.example.internal"}, {}, "prod_target_refused"),
        ({}, {"environment": "prod"}, "prod_target_refused"),
        ({}, {"environment": "dev"}, "channel_mismatch"),
        ({}, {"git_sha": "f" * 40}, "candidate_mismatch"),
        ({}, {"available": False}, "target_unavailable"),
        ({"candidate": {"source_sha": "short", "image_digest": DIGEST}}, {}, "candidate_identity_invalid"),
    ],
)
def test_candidate_and_channel_must_match_qualification(
    tmp_path: Path, override: dict[str, Any], channel_kwargs: dict[str, Any], reason: str
) -> None:
    channel = FakeTestChannel(**channel_kwargs)
    receipt = _run(tmp_path, channel, **override)

    assert receipt["passed"] is False and receipt["outcome"] == "refused" and receipt["refusal"] == reason
    assert not [c for c in channel.calls if c[0] == "POST"], "no voice turn may reach a refused target"

    # Unqualified or foreign-candidate qualification evidence refuses before any request.
    for field, value, expected in (("status", "pending", "route_or_instance_unqualified"),
                                   ("source_sha", "9" * 40, "qualification_candidate_mismatch"),
                                   ("channel", "prod", "qualification_channel_mismatch")):
        payload = _qualification(tmp_path)
        payload["qualification"]["route"][field] = value
        fresh = FakeTestChannel()
        assert vta.run_acceptance(payload, fresh, base_dir=tmp_path)["refusal"] == expected
        assert fresh.calls == []

    # Candidate drift during the run fails the run after its turns; never a pass or a pre-turn refusal.
    drifting = FakeTestChannel()
    drifting.drift_after_voice = True
    drifted = _run(tmp_path, drifting)
    assert drifted["passed"] is False and drifted["outcome"] == "failed" and drifted["refusal"] == "candidate_drift"

    class LostAfter(FakeTestChannel):
        def get(self, path: str, query: Mapping[str, str] | None = None) -> tuple[int, str, bytes]:
            if path == "/version" and len(self.voice_turns) == 2:
                raise ConnectionError("gone")
            return super().get(path, query)

    lost = _run(tmp_path, LostAfter())
    assert lost["outcome"] == "failed" and lost["refusal"] == "post_run_target_unavailable"

    # A digest reported by the target must equal the qualified digest.
    class Digest(FakeTestChannel):
        reported = DIGEST

        def get(self, path: str, query: Mapping[str, str] | None = None) -> tuple[int, str, bytes]:
            if path == "/version":
                return 200, "application/json", json.dumps({"git_sha": SHA, "image_digest": self.reported}).encode()
            return super().get(path, query)

    assert _run(tmp_path, Digest())["observed_before"]["image_digest_source"] == "observed"
    other = Digest()
    other.reported = "sha256:" + "0" * 64
    assert _run(tmp_path, other)["refusal"] == "candidate_mismatch" and not other.voice_turns

    # Health must report the same SHA; a missing version is not a match.
    no_version = FakeTestChannel()
    no_version.health_override = {"version": None}
    assert _run(tmp_path, no_version)["refusal"] == "candidate_mismatch" and not no_version.voice_turns

    # The image digest must be bound by a fresh, matching TEST topology observation.
    for topology, expected in ((_topology(digest="sha256:" + "1" * 64), "deployment_image_mismatch"),
                               (_topology(age=timedelta(hours=30)), "deployment_identity_unavailable"),
                               (_topology(refusals=["image_unverified"]), "deployment_identity_refused"),
                               ({**_topology(), "channels": [
                                   {**c, "health_version": "version:1.2.3"} for c in _topology()["channels"]]},
                                "deployment_identity_unverified")):
        fresh = FakeTestChannel()
        payload = _qualification(tmp_path / "t", topology=topology)
        assert vta.run_acceptance(payload, fresh, base_dir=tmp_path / "t")["refusal"] == expected
        assert fresh.calls == []

    # Evidence channel casing is normalized like the top-level channel.
    upper = _qualification(tmp_path, channel="TEST")
    upper["qualification"]["route"]["channel"] = "TEST"
    assert vta.run_acceptance(upper, FakeTestChannel(), base_dir=tmp_path)["passed"] is True


def test_receipt_is_candidate_bound_and_secret_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt = _run(tmp_path, FakeTestChannel())

    assert receipt["schema"] == "voice_test_channel_acceptance.v1"
    assert receipt["candidate"] == {"source_sha": SHA, "image_digest": DIGEST}
    assert receipt["observed_before"] == receipt["observed_after"] == {
        "channel": "test", "source_sha": SHA, "health_ok": True, "image_digest_source": "channel_topology"}
    payload = _qualification(tmp_path)
    assert receipt["qualification_sha256"] == hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert receipt["deployment"]["source_image_identity"].endswith("@" + DIGEST)
    assert receipt["deployment"]["source_ref"] == "qualification:voice-6234"
    assert receipt["routes"] == ROUTES
    assert receipt["qualification"]["route"]["ref"].endswith("#5977")
    assert receipt["qualification"]["instance"]["ref"].endswith("#6190")
    assert receipt["synthetic_actor"] == "synthetic-voice-acceptance-v1"
    assert set(receipt["languages"]) == {"sv", "en"}
    assert all(receipt["languages"][x]["citations"] for x in ("sv", "en"))

    text = json.dumps(receipt)
    for forbidden in (*TRANSCRIPTS.values(), ANSWER, "RIFF", TOKEN, "Bearer"):
        assert forbidden not in text
    vta.assert_receipt_secret_free(receipt)
    with pytest.raises(vta.VoiceAcceptanceRefusal):
        vta.assert_receipt_secret_free({**receipt, "extra": {"transcript": "x"}})
    with pytest.raises(vta.VoiceAcceptanceRefusal):
        vta.assert_receipt_secret_free({**receipt, "audio": b"RIFF"})

    # Secret-looking server identifiers are hashed, never echoed and never fatal.
    odd = FakeTestChannel()
    odd.sources_override = [{"uuid": "u", "path": SOURCES["sv"]}, {"uuid": "token=abc123", "path": "notes/sk-ref.md"}]
    odd_receipt = _run(tmp_path, odd)
    assert odd_receipt["languages"]["sv"]["status"] == "passed"
    assert "abc123" not in json.dumps(odd_receipt) and "sk-ref" not in json.dumps(odd_receipt)

    # A credential-bearing qualification input is refused, and the CLI never records the token.
    leaked = _qualification(tmp_path, api_url="https://user:pw@ygg-test.example.internal")
    assert vta.run_acceptance(leaked, FakeTestChannel(), base_dir=tmp_path)["refusal"] == "qualification_contains_secret"

    path = tmp_path / "qualification.json"
    path.write_text(json.dumps(_qualification(tmp_path)))
    out = tmp_path / "receipt.json"
    monkeypatch.setenv(vta.AUTH_TOKEN_ENV, TOKEN)
    seen: list[str | None] = []

    class CliTransport(FakeTestChannel):
        def __init__(self, origin: str, *, token: str | None = None, **_: Any) -> None:
            super().__init__()
            seen.append(token)

    monkeypatch.setattr(vta, "HttpTransport", CliTransport)
    assert vta.main(["--qualification", str(path), "--out", str(out)]) == 0
    assert seen == [TOKEN]
    written = out.read_text()
    assert TOKEN not in written and json.loads(written)["passed"] is True
    assert out.stat().st_mode & 0o077 == 0
    # An unexpected verifier error still yields a complete failed receipt, never an empty file.
    def boom(*_: Any, **__: Any) -> dict[str, Any]:
        raise OSError("disk")

    original = vta.run_acceptance
    monkeypatch.setattr(vta, "run_acceptance", boom)
    errored = tmp_path / "errored.json"
    assert vta.main(["--qualification", str(path), "--out", str(errored)]) == 1
    assert json.loads(errored.read_text())["refusal"] == "verifier_error_OSError"
    monkeypatch.setattr(vta, "run_acceptance", original)

    # An existing --out path is refused before any voice turn is sent.
    seen.clear()
    with pytest.raises(FileExistsError):
        vta.main(["--qualification", str(path), "--out", str(out)])
    assert seen == []


def test_verifier_has_no_configuration_or_prod_write_path(tmp_path: Path) -> None:
    # The real transport admits only identity/audio GETs and the voice POST.
    sent: list[tuple[str, str, Mapping[str, str]]] = []

    class Response:
        status = 200
        headers = {"content-type": "application/json"}

        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self, _: int) -> bytes:
            return self._body

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

    def opener(request: Any, timeout: float) -> Response:
        sent.append((request.get_method(), request.full_url, dict(request.header_items())))
        return Response(b"{}")

    # The default opener never routes through an environment proxy.
    from urllib.request import ProxyHandler

    default = vta.HttpTransport("https://ygg-test.example.internal")
    handlers = default._open.__self__.handlers  # type: ignore[attr-defined]
    assert not [h for h in handlers if isinstance(h, ProxyHandler) and h.proxies]

    with pytest.raises(vta.VoiceAcceptanceRefusal, match="bearer_requires_https"):
        vta.HttpTransport("http://ygg-test.example.internal", token=TOKEN, opener=opener)

    transport = vta.HttpTransport("https://ygg-test.example.internal", token=TOKEN, opener=opener)
    for method, path in (("GET", "/api/vault/select"), ("GET", "/api/settings"), ("GET", "/api/companion/tts/plan")):
        with pytest.raises(vta.VoiceAcceptanceRefusal, match="transport_path_refused"):
            transport._send(method, path)
    for method, path in (("POST", "/api/vault/select"), ("PUT", "/api/ask/voice"), ("DELETE", "/version"),
                         ("POST", "/api/companion/tts/synthesize")):
        with pytest.raises(vta.VoiceAcceptanceRefusal, match="transport_path_refused"):
            transport._send(method, path, b"")
    assert sent == []

    transport.get("/version")
    transport.post_voice(FIXTURE_AUDIO["sv"], "audio/wav", {"end_session": "true"})
    assert [(m, u) for m, u, _ in sent] == [("GET", "https://ygg-test.example.internal/version"),
                                            ("POST", "https://ygg-test.example.internal/api/ask/voice")]
    assert sent[1][2]["Content-type"].startswith("multipart/form-data; boundary=")

    # A full run only uses the allowlisted read/voice surface.
    channel = FakeTestChannel()
    _run(tmp_path, channel)
    assert {c for c in channel.calls} <= {("GET", "/version"), ("GET", "/api/health"), ("POST", "/api/ask/voice")} | {
        ("GET", p) for _, p in channel.calls if vta.AUDIO_PATH.fullmatch(p)}

    # The module imports no deployment, configuration, credential or process seam.
    tree = ast.parse(Path(vta.__file__).read_text())
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    modules = {(node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {m.split(".")[0] for m in modules}
    assert imported.isdisjoint({"subprocess", "shutil", "socket", "docker", "paramiko"})
    # The only Product import is the pure, read-only topology validator.
    assert {m for m in modules if m.startswith("app")} == {"app.ops.product_tars_channel_topology"}
    source = Path(vta.__file__).read_text()
    for forbidden in ("subprocess", "os.system", "os.remove", "unlink(", "write_text(", "dotenv"):
        assert forbidden not in source
