"""SCREEN-02 enforcement: local-only routing + gated raw read at the call site (#3344).

AC2. This asserts the two privacy-seam properties **at the production
derivation call site** (`derive_activity_observations`), not on a helper in
isolation:

1. the route compiled for task kind `heimdal.screen_derivation` is
   `paid_eligible: false` and resolves to a local-tier provider; a census that
   declares the task kind paid-eligible is *rejected* by the compiler before
   any raw byte is read (RUNTIME_MODEL_POSTURE §1/§4.2 always-on-local floor);
2. raw evidence is reached only through the gated read path
   (`app.heimdal.raw_read_gate.read_raw_record`), leaving one receipt per
   frame -- and a reader that is not on the allowlist gets no bytes and no
   observation (HEIM-5).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest

from app.components.settings.providers_loader import load_provider_census
from app.heimdal import screen_derivation
from app.heimdal.observation_log import count_observations
from app.heimdal.raw_read_gate import RawReadRefusedError, all_raw_read_receipts
from app.heimdal.screen_derivation import (
    TASK_KIND,
    PaidRouteRejectedError,
    derive_activity_observations,
    resolve_derivation_route,
)
from tests.heimdal._screen_derivation_fixtures import (
    RAW_STORE_KEY,
    land_frame,
    reset_screen_derivation_state,
    stub_vision_runner,
)

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def reset(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_screen_derivation_state(monkeypatch)


def _census_with_paid_task_kind() -> Any:
    """The shipped census, mutated so a paid provider claims this task kind."""
    census = load_provider_census()
    paid = next(provider for provider in census.providers if provider.tier == "paid")
    paid.paid_eligible_task_kinds = [*paid.paid_eligible_task_kinds, TASK_KIND]
    return census


def test_screen_derivation_is_paid_ineligible_and_reads_raw_gated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = land_frame(frame="frame-routing", observed_at="2026-07-11T10:00:00Z")

    # --- success path: production call site compiles a local route and reads gated
    reads: List[dict] = []
    real_read = screen_derivation.read_raw_record

    def spy_read(raw_ref: str, **kwargs: Any) -> Any:
        reads.append({"raw_ref": raw_ref, **kwargs})
        return real_read(raw_ref, **kwargs)

    monkeypatch.setattr(screen_derivation, "read_raw_record", spy_read)

    tick = derive_activity_observations(
        [frame],
        episode_id="screen-session-routing",
        vision_runner=stub_vision_runner(),
        key=RAW_STORE_KEY,
    )

    assert tick.route.task_kind == TASK_KIND
    assert tick.route.paid_eligible is False
    assert tick.route.tier == "local"
    assert tick.route.provider == "ollama"
    assert tick.observations_published == 1

    # The one raw read went through the gate, with this stage's reader identity.
    assert len(reads) == 1
    assert reads[0]["raw_ref"] == frame.raw_ref
    assert reads[0]["reader"] == "screen_derivation"
    assert reads[0]["purpose"] == "screen_derivation"

    receipts = all_raw_read_receipts()
    assert len(receipts) == 1
    assert receipts[0].reader == "screen_derivation"
    assert receipts[0].raw_ref == frame.raw_ref

    # The shipped census itself keeps this always-on task kind paid-ineligible.
    assert resolve_derivation_route().paid_eligible is False

    # --- negative path 1: a paid assignment is rejected by the compiler, before any read
    monkeypatch.setattr(screen_derivation, "load_provider_census", _census_with_paid_task_kind)
    reads.clear()
    before = count_observations()
    with pytest.raises(PaidRouteRejectedError, match=TASK_KIND):
        derive_activity_observations(
            [land_frame(frame="frame-paid", observed_at="2026-07-11T10:01:00Z")],
            episode_id="screen-session-routing",
            vision_runner=stub_vision_runner(),
            key=RAW_STORE_KEY,
        )
    assert reads == []
    assert count_observations() == before
    assert len(all_raw_read_receipts()) == 1

    monkeypatch.setattr(screen_derivation, "load_provider_census", load_provider_census)

    # --- negative path 2: no ungated raw path exists to fall back to (HEIM-5)
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "")
    with pytest.raises(RawReadRefusedError):
        derive_activity_observations(
            [land_frame(frame="frame-refused", observed_at="2026-07-11T10:02:00Z")],
            episode_id="screen-session-routing",
            vision_runner=stub_vision_runner(),
            key=RAW_STORE_KEY,
        )
    assert count_observations() == before
    assert len(all_raw_read_receipts()) == 1


def test_raw_frames_refuse_a_destination_that_is_not_host_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production egress path: the census proves a name, this proves a socket.

    A `tier: local` census entry says nothing about where `OLLAMA_BASE_URL`
    actually points. Success path: a loopback endpoint (and an explicitly
    operator-declared host-local one) is accepted. Negative path: a remote
    endpoint is refused *and no request is issued* -- the frame is never
    transmitted, so `DECLARED_EGRESS[raw_class_egress] is False` stays true.
    """
    posts: List[Any] = []

    def spy_post(endpoint: str, body: Any) -> str:
        posts.append(endpoint)
        return '{"summary": "Editing a note", "goal": "write", "confidence": 0.5}'

    monkeypatch.setattr(screen_derivation, "_post_local_vision", spy_post)
    for variable in ("OLLAMA_HOST", "OLLAMA_URL"):
        monkeypatch.delenv(variable, raising=False)

    # --- negative path: a remote destination is refused before any transmission
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://vision.example.com")
    monkeypatch.delenv(screen_derivation.HOST_LOCAL_VISION_ALLOWLIST_ENV, raising=False)
    with pytest.raises(screen_derivation.RawEgressRefusedError, match="vision.example.com"):
        derive_activity_observations(
            [land_frame(frame="frame-remote", observed_at="2026-07-11T10:10:00Z")],
            episode_id="screen-session-egress",
            key=RAW_STORE_KEY,
        )
    assert posts == [], "a frame was transmitted to a non-host-local destination"
    assert count_observations() == 0

    # --- success path: loopback is accepted and reaches the local model
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    tick = derive_activity_observations(
        [land_frame(frame="frame-loopback", observed_at="2026-07-11T10:11:00Z")],
        episode_id="screen-session-egress",
        key=RAW_STORE_KEY,
    )
    assert tick.observations_published == 1
    assert posts == ["http://127.0.0.1:11434"]

    # --- completeness: a container-network host is host-local only when declared
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    with pytest.raises(screen_derivation.RawEgressRefusedError):
        screen_derivation.resolve_local_vision_endpoint()
    monkeypatch.setenv(screen_derivation.HOST_LOCAL_VISION_ALLOWLIST_ENV, "ollama")
    assert screen_derivation.resolve_local_vision_endpoint() == "http://ollama:11434"


#: Endpoint shapes that have historically split one URL parser from another,
#: or that merely look host-local. Which of these a given `urllib.parse` /
#: `urllib3` version disagrees on is a moving target, so this asserts the
#: invariant rather than any one parser's quirk.
ADVERSARIAL_ENDPOINTS = [
    # Backslash and bracket shapes split `urllib.parse` from `urllib3`. Which
    # direction they split in is version-dependent -- on urllib3 2.5.0 /
    # CPython 3.12, `http://evil.example.com\@127.0.0.1` reads as loopback to
    # `urllib.parse` while `requests` dials `evil.example.com`, which is
    # exactly the exploitable direction.
    "http://evil.example.com\\@127.0.0.1",
    "http://127.0.0.1:11434\\@evil.example.com",
    "http://127.0.0.1\\evil.example.com",
    "http://evil.example.com]@127.0.0.1",
    "http://127.0.0.1:11434[@evil.example.com",
    "http://127.0.0.1%evil.example.com",
    "http://127.0.0.1:evil.example.com",
    "http://127.0.0.1@evil.example.com",
    "http://localhost#@evil.example.com",
    "http://evil.example.com#@127.0.0.1",
    "http://localhost.evil.example.com",
    "http://127.0.0.1.evil.example.com",
    "http://2130706433",
    "http://0177.0.0.1",
    "http://127.0.0.2",
    "http://0.0.0.0",
    "http://[::ffff:127.0.0.1]",
    "//evil.example.com",
    "http://evil.example.com/../127.0.0.1",
]


def test_the_validated_host_is_the_host_the_client_actually_dials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validation and transmission must read one parser, never two.

    A validator that parses the endpoint with a different library than the HTTP
    client uses can approve one destination while the frame goes to another --
    silently, because the other end's response is consumed as the model's
    answer and published as a governed observation. This asserts the invariant
    that survives parser-version drift: for every adversarial shape, EITHER the
    endpoint is refused, OR the host the client would actually dial is
    host-local. There is no third outcome.
    """
    import requests
    from urllib3.util import parse_url

    for variable in ("OLLAMA_BASE_URL", "OLLAMA_HOST", "OLLAMA_URL"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv(screen_derivation.HOST_LOCAL_VISION_ALLOWLIST_ENV, raising=False)

    session = screen_derivation.local_vision_session()
    for endpoint in ADVERSARIAL_ENDPOINTS:
        monkeypatch.setenv("OLLAMA_BASE_URL", endpoint)
        try:
            resolved = screen_derivation.resolve_local_vision_endpoint()
        except (
            screen_derivation.RawEgressRefusedError,
            screen_derivation.LocalVisionUnavailableError,
        ):
            continue
        # Not refused -> the host the CLIENT will dial must be host-local.
        # Deliberately re-derived here with urllib3 (what `requests` actually
        # resolves with) rather than through the module's own helper: reading
        # the module's parser would make this test agree with a wrong
        # validator instead of catching it.
        prepared = session.prepare_request(
            requests.Request("POST", resolved.rstrip("/") + "/api/chat", json={})
        )
        try:
            dialled = (parse_url(prepared.url).host or "").strip().lower().strip("[]")
        except Exception:
            continue  # the client itself cannot dial this; nothing is transmitted
        assert dialled in screen_derivation._LOOPBACK_HOSTNAMES, (
            f"endpoint {endpoint!r} was accepted but the client would dial {dialled!r}"
        )


def test_the_send_itself_refuses_a_destination_that_is_not_host_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate adjacent to the socket is load-bearing on its own.

    `resolve_local_vision_endpoint` is the fail-fast check; this is the one
    that cannot be bypassed, because it reads the exact prepared URL. Asserted
    against `_post_local_vision` directly: even handed an endpoint that never
    passed the early check, it must refuse before sending. That is what makes
    the two checks defence in depth rather than one check written twice.
    """
    sent: List[Any] = []
    real_session = screen_derivation.local_vision_session()

    class _Session:
        def prepare_request(self, request: Any) -> Any:
            return real_session.prepare_request(request)

        def send(self, prepared: Any, **kwargs: Any) -> Any:  # pragma: no cover - must not run
            sent.append(prepared.url)
            raise AssertionError("a frame was sent to an unvalidated destination")

        def close(self) -> None:
            return None

    monkeypatch.setattr(screen_derivation, "local_vision_session", lambda: _Session())
    monkeypatch.delenv(screen_derivation.HOST_LOCAL_VISION_ALLOWLIST_ENV, raising=False)

    with pytest.raises(screen_derivation.RawEgressRefusedError, match="evil.example.com"):
        screen_derivation._post_local_vision(
            "http://evil.example.com", {"model": "llava:7b", "messages": []}
        )
    assert sent == []


def test_every_endpoint_variable_is_guarded_not_just_the_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All three endpoint variables are validated, not only `OLLAMA_BASE_URL`."""
    for variable in ("OLLAMA_BASE_URL", "OLLAMA_HOST", "OLLAMA_URL"):
        for other in ("OLLAMA_BASE_URL", "OLLAMA_HOST", "OLLAMA_URL"):
            monkeypatch.delenv(other, raising=False)
        monkeypatch.delenv(screen_derivation.HOST_LOCAL_VISION_ALLOWLIST_ENV, raising=False)
        monkeypatch.setenv(variable, "http://evil.example.com")
        with pytest.raises(screen_derivation.RawEgressRefusedError):
            screen_derivation.resolve_local_vision_endpoint()


def test_local_vision_refuses_to_follow_a_redirect_off_the_validated_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A validated destination must stay validated for every hop.

    A 3xx from the local endpoint would otherwise make `requests` resend the
    frame body to a `Location` the endpoint validator never saw -- the same
    escape the proxy guard closes, one hop later. The request must not follow
    it, and the refusal must surface as an egress refusal rather than be
    laundered into a generic "model unavailable".
    """

    class _Redirect:
        is_redirect = True
        is_permanent_redirect = False
        headers = {"Location": "https://vision.example.com/api/chat"}

        def raise_for_status(self) -> None:  # pragma: no cover - never reached
            raise AssertionError("redirect must be refused before raise_for_status")

        def json(self) -> Any:  # pragma: no cover - never reached
            raise AssertionError("redirect must be refused before the body is read")

    sent: List[Any] = []
    real_session = screen_derivation.local_vision_session()

    class _Session:
        trust_env = True

        def prepare_request(self, request: Any) -> Any:
            return real_session.prepare_request(request)

        def send(self, prepared: Any, **kwargs: Any) -> Any:
            sent.append(prepared.url)
            assert kwargs.get("allow_redirects") is False, "redirects must not be followed"
            return _Redirect()

        def close(self) -> None:
            return None

    monkeypatch.setattr(screen_derivation, "local_vision_session", lambda: _Session())
    for variable in ("OLLAMA_HOST", "OLLAMA_URL"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    with pytest.raises(screen_derivation.RawEgressRefusedError, match="redirect"):
        derive_activity_observations(
            [land_frame(frame="frame-redirect", observed_at="2026-07-11T10:20:00Z")],
            episode_id="screen-session-redirect",
            key=RAW_STORE_KEY,
        )
    assert len(sent) == 1, "exactly one request should have been attempted"
    assert count_observations() == 0


def test_local_vision_request_ignores_ambient_proxy_configuration() -> None:
    """A validated loopback address must not be re-routed by an ambient proxy.

    `requests` honours HTTP_PROXY/HTTPS_PROXY/ALL_PROXY by default, which would
    carry a loopback-addressed raw frame off the host after the address itself
    was proven host-local. The session must disable `trust_env`.
    """
    assert screen_derivation.local_vision_session().trust_env is False


def test_derivation_module_has_no_paid_provider_code_path() -> None:
    """Completeness: the stage cannot degrade into a cloud route.

    Mirrors the ASR stage's "there is no cloud code path in this module at all
    to silently fall into" posture -- the module names no paid provider and
    reaches no generic, env-routed LLM dispatcher.
    """
    text = Path(screen_derivation.__file__).read_text(encoding="utf-8")
    for forbidden in ("openai", "anthropic", "deepseek", "app.llm.adapter", "app.services.llm"):
        assert forbidden not in text, f"screen derivation must not reference {forbidden}"
