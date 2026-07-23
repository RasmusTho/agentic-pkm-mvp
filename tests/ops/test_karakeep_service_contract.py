"""Managed Karakeep service deployment contract (KMA-02, #3373).

Asserts the repo-owned deployment manifest is pinned, durable, health-checked,
and secret-free, and that the fail-loud fetch gate blocks Heimdal acquisition on
absent config or red health while leaving Mimer replay of already-published
evidence available.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest

from app.heimdal.karakeep_service import (
    KarakeepServiceConfigError,
    KarakeepServiceUnhealthyError,
    assert_fetch_ready,
)
from app.release_channels.channel_isolation_preflight import _load_compose

pytestmark = pytest.mark.not_pg

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO_ROOT / "docker-compose.karakeep.yml"
_ENV_EXAMPLE = _REPO_ROOT / "config" / "karakeep.env.example"
_KARAKEEP_SERVICE = "karakeep"


def _services() -> dict:
    return _load_compose(_MANIFEST)["services"]


def test_service_manifest_is_pinned_persistent_and_health_checked() -> None:
    compose = _load_compose(_MANIFEST)
    services = compose["services"]
    karakeep = services[_KARAKEEP_SERVICE]

    # Pinned image/version -- never a floating tag.
    image = karakeep["image"]
    assert ":" in image, "image must carry an explicit version/digest, not a bare repository"
    assert not image.endswith(":latest"), "image must be pinned, not :latest"
    tag = image.rsplit(":", 1)[1]
    assert tag and tag != "latest"

    # Restart supervision.
    assert karakeep["restart"] == "unless-stopped"

    # Healthcheck present with an executable test.
    healthcheck = karakeep.get("healthcheck") or {}
    assert healthcheck.get("test"), "karakeep service must declare a healthcheck test"

    # Durable named volume for the service data, declared at the top level so it
    # survives restart/update (only `down -v` removes it).
    service_volumes = karakeep.get("volumes") or []
    named_mounts = [v for v in service_volumes if isinstance(v, str) and not v.startswith("/") and not v.startswith(".")]
    assert named_mounts, "karakeep service must mount a durable named volume"
    top_level_volumes = compose.get("volumes") or {}
    for mount in named_mounts:
        volume_name = mount.split(":", 1)[0]
        assert volume_name in top_level_volumes, f"named volume {volume_name} must be declared"

    # The search dependency is likewise pinned and durably backed.
    meili = services["karakeep-meilisearch"]
    assert not meili["image"].endswith(":latest")
    assert any(
        isinstance(v, str) and v.split(":", 1)[0] in top_level_volumes
        for v in (meili.get("volumes") or [])
    )


def test_unhealthy_service_blocks_heimdal_fetch_not_mimer_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    from app.heimdal.observation_log import reset_memory_observation_log
    from app.heimdal.publish import publish_full_observation, read_observations_for_consumer

    reset_memory_observation_log()

    ready_env = {
        "KARAKEEP_BASE_URL": "http://127.0.0.1:3000",
        "KARAKEEP_API_TOKEN": "placeholder-token",
    }

    # 1. Absent required config -> Heimdal fetch is refused before any egress.
    with pytest.raises(KarakeepServiceConfigError) as config_exc:
        assert_fetch_ready(env={"KARAKEEP_BASE_URL": "http://127.0.0.1:3000"})
    assert "KARAKEEP_API_TOKEN" in str(config_exc.value)

    # 2. Config present but service health red -> fetch refused.
    def _unhealthy(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request, text="unavailable")

    with pytest.raises(KarakeepServiceUnhealthyError):
        assert_fetch_ready(env=ready_env, http=httpx.Client(transport=httpx.MockTransport(_unhealthy)))

    # 3. Healthy service -> gate passes.
    def _healthy(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, text="ok")

    assert_fetch_ready(env=ready_env, http=httpx.Client(transport=httpx.MockTransport(_healthy)))

    # 4. Mimer replay is independent of the service gate: already-published
    #    evidence remains readable through the consumer seam while the service
    #    is down (KMA-INV-4).
    published = publish_full_observation(
        topic="heimdal.observation.published",
        payload={
            "observation_id": "karakeep:svc-1:aa:bb",
            "episode_id": "karakeep:svc-1",
            "observed_at_start": "2026-07-10T08:15:00+02:00",
            "attributions": [
                {"mention_id": "operator-recorder", "role": "recorder", "resolution": "resolved", "basis": "capture_context"}
            ],
            "content": "already durable",
            "confidence": {"source_integrity": {"score": 1.0, "calibration": "by_construction"}},
            "provenance": {
                "sensor": "karakeep_rest",
                "capture_chain": ["karakeep", "karakeep_rest", "heimdal_karakeep_adapter"],
                "content_identity": "sha256:aa",
            },
            "sensitivity": "private",
            "consent": {"basis": "self_record", "grant_ref": "grant:karakeep-source-ingestion"},
        },
        source="heimdal_karakeep_adapter",
    )
    assert published is not None

    # Service is "down": the gate refuses fetch...
    with pytest.raises(KarakeepServiceUnhealthyError):
        assert_fetch_ready(env=ready_env, http=httpx.Client(transport=httpx.MockTransport(_unhealthy)))
    # ...but Mimer replay of the durable evidence still works.
    replayed = read_observations_for_consumer("mimer.candidate_projector")
    assert [r.envelope["payload"]["observation_id"] for r in replayed] == ["karakeep:svc-1:aa:bb"]


def test_service_manifest_is_health_checked_and_secret_free() -> None:
    manifest_text = _MANIFEST.read_text(encoding="utf-8")
    example_text = _ENV_EXAMPLE.read_text(encoding="utf-8")

    # Health-checked: every service in the manifest declares a healthcheck test.
    for name, service in _services().items():
        assert (service.get("healthcheck") or {}).get("test"), f"{name} must declare a healthcheck"

    # Secret-free committed manifest: secrets/endpoints ride the env_file, never
    # a literal value in the compose file.
    assert "./config/karakeep.env" in manifest_text
    lowered = manifest_text.lower()
    for secret_marker in ("nextauth_secret:", "meili_master_key:", "karakeep_api_token:"):
        assert secret_marker not in lowered, f"{secret_marker} must not carry a literal value in the manifest"

    # The committed template uses placeholders only -- no real credential values.
    assert "KARAKEEP_API_TOKEN=REPLACE_ME" in example_text
    assert "NEXTAUTH_SECRET=REPLACE_ME" in example_text
    assert "MEILI_MASTER_KEY=REPLACE_ME" in example_text

    # The filled-in operator config is never committed; only the template is.
    tracked = subprocess.run(
        ["git", "ls-files", "config/karakeep.env", "config/karakeep.env.example"],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert "config/karakeep.env.example" in tracked
    assert "config/karakeep.env" not in tracked

    # A malformed operator endpoint is handled secret-safely: an httpx.InvalidURL
    # (whose message would embed the endpoint) is caught and reported as a status
    # class only, never surfaced.
    from app.heimdal.karakeep_service import check_service_health

    def _raise_invalid(request: httpx.Request) -> httpx.Response:
        raise httpx.InvalidURL("No host in URL 'http://karakeep.private.example'")

    health = check_service_health(
        "http://placeholder", http=httpx.Client(transport=httpx.MockTransport(_raise_invalid))
    )
    assert not health.healthy
    assert health.reason == "invalid_endpoint"

    # Logs/errors from the gate are secret-safe: a missing-config error names the
    # variable but never a value; a health error names a status class, not the URL.
    try:
        assert_fetch_ready(env={"KARAKEEP_BASE_URL": "https://karakeep.private.example"})
    except KarakeepServiceConfigError as exc:
        assert "https://karakeep.private.example" not in str(exc)
        assert "KARAKEEP_API_TOKEN" in str(exc)
    else:  # pragma: no cover - the token is absent, so the gate must raise
        raise AssertionError("expected a config error for the absent token reference")
