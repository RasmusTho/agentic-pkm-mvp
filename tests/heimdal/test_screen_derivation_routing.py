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


def test_derivation_module_has_no_paid_provider_code_path() -> None:
    """Completeness: the stage cannot degrade into a cloud route.

    Mirrors the ASR stage's "there is no cloud code path in this module at all
    to silently fall into" posture -- the module names no paid provider and
    reaches no generic, env-routed LLM dispatcher.
    """
    source = screen_derivation.__file__
    with open(source, "r", encoding="utf-8") as handle:
        text = handle.read()
    for forbidden in ("openai", "anthropic", "deepseek", "app.llm.adapter", "app.services.llm"):
        assert forbidden not in text, f"screen derivation must not reference {forbidden}"
