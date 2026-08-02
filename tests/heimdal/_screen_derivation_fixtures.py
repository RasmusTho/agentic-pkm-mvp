"""Shared fixtures for the SCREEN-02 derivation tests (#3344).

Every screen-derivation test needs the same durable setup: an in-memory
Heimdal backend, a registered screen sensor, an active `screen_always_on`
grant, and one or more real frame bundles landed through the SCREEN-01
ingress (`app.heimdal.screen_capture.ingest_screen_bundle`) so the raw
records the derivation stage reads are the ones production actually writes,
not hand-built rows.
"""

from __future__ import annotations

import secrets
from typing import Any, Dict

from app.heimdal.capture_adapter import register_sensor
from app.heimdal.consent_ledger import grant_consent, reset_memory_consent_ledger
from app.heimdal.observation_log import reset_memory_observation_log
from app.heimdal.raw_read_gate import reset_memory_raw_read_receipts
from app.heimdal.raw_store import all_raw_records, reset_memory_raw_store
from app.heimdal.screen_capture import SCREEN_CAPTURE_SCOPE, ingest_screen_bundle
from app.heimdal.screen_context_providers import reset_context_providers
from app.heimdal.screen_derivation import ScreenFrame, screen_frame_from_raw_record

RAW_STORE_KEY = bytes.fromhex(secrets.token_hex(32))
SENSOR_ADAPTER = "screen-test"
SENSOR_VERSION = "v1"
MACHINE = "mac-1"
GRANT_REF = "screen-test-grant"


def reset_screen_derivation_state(monkeypatch: Any) -> None:
    """Reset every durable Heimdal surface this stage touches, then re-seed consent."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", RAW_STORE_KEY.hex())
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "screen_derivation")
    reset_memory_raw_store()
    reset_memory_consent_ledger()
    reset_memory_observation_log()
    reset_memory_raw_read_receipts()
    reset_context_providers()
    register_sensor(SENSOR_ADAPTER, SENSOR_VERSION)
    grant_consent(
        grant_ref=GRANT_REF,
        scope=SCREEN_CAPTURE_SCOPE,
        basis="screen_always_on",
        granted_by="operator",
    )


def screen_bundle(
    *,
    frame: str,
    app: str = "Obsidian",
    window: str = "ERE spec.md",
    scope: str = "work",
    machine: str = MACHINE,
) -> Dict[str, Any]:
    """One SCREEN-01 raw-capture bundle carrying its frontmost-app metadata."""
    return {
        "bundle_shape": "raw_capture_bundle",
        "sensor": {"adapter": SENSOR_ADAPTER, "version": SENSOR_VERSION, "machine": machine},
        "capture_chain": ["macos_screen_observer", "screen_capture_post"],
        "raw": {"frame": frame, "app": app, "window": window, "scope": scope},
    }


def land_frame(
    *,
    frame: str,
    observed_at: str,
    app: str = "Obsidian",
    window: str = "ERE spec.md",
    scope: str = "work",
    machine: str = MACHINE,
) -> ScreenFrame:
    """Land one frame through the real SCREEN-01 ingress and return its stage handle."""
    bundle = screen_bundle(frame=frame, app=app, window=window, scope=scope, machine=machine)
    ingest_screen_bundle(bundle, key=RAW_STORE_KEY)
    record = all_raw_records()[-1]
    return screen_frame_from_raw_record(record, observed_at=observed_at)


def stub_vision_runner(
    *,
    summary: str | None = None,
    goal: str = "draft the ERE spec",
    confidence: float = 0.72,
) -> Any:
    """A deterministic stand-in for the local vision model.

    Shaped exactly like the production local-vision call's return value
    (`summary`/`goal`/`mentions`/`confidence`), and it echoes the dimensions
    the context providers contributed so a provider change is visible in the
    derived text.
    """
    calls: list[Any] = []

    def runner(request: Any) -> Dict[str, Any]:
        calls.append(request)
        dimensions = dict(request.dimensions)
        text = summary or (
            f"Editing {dimensions.get('window', 'something')} in {dimensions.get('app', 'an app')}"
        )
        return {
            "summary": text,
            "goal": goal,
            "mentions": [{"surface_form": dimensions.get("app", "unknown"), "kind_hint": "app"}],
            "confidence": confidence,
        }

    runner.calls = calls  # type: ignore[attr-defined]
    return runner
