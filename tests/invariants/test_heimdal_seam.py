"""HEIM-12 `heim_declared_egress` -- the seam's declared egress posture.

The §8-reserved home for HEIM-12 (`docs/HEIMDAL/FABLE_COMPANION.md` §8,
reserved by `tests/heimdal/test_invariants_heim.py`). SCREEN-02 (#3344) is the
first Heimdal stage to carry a **structured, machine-checkable** egress
declaration rather than prose in a docstring, so the static half of HEIM-12
graduates here for that stage.

Still reserved in the interim skeleton module, deliberately not claimed here:
the per-adapter posture for the voice-memo capture adapter (prose-only today)
and the future network-boundary probe. This file asserts exactly what is
enforced now -- the screen-derivation stage declares zero raw-class egress,
and the route its production call site compiles cannot leave the host.
"""

from __future__ import annotations

import pytest

from app.components.settings.providers_loader import load_provider_census
from app.heimdal import screen_derivation
from app.heimdal.screen_derivation import (
    DECLARED_EGRESS,
    TASK_KIND,
    PaidRouteRejectedError,
    resolve_derivation_route,
)
from tests.invariants._helpers import read_doc

pytestmark = pytest.mark.not_pg

_STAGE_DOC = "docs/HEIMDAL_SCREEN_STREAM/DERIVE_ACTIVITY_OBSERVATIONS.md"


def test_declared_egress() -> None:
    """The screen-derivation stage declares zero raw egress, structurally.

    Success path: the declaration exists, names the stage, and names no raw
    egress; the compiled route is local-tier and paid-ineligible. Negative
    path: a census that makes the stage paid-eligible is rejected outright,
    so there is no declared-but-reachable cloud destination for raw pixels.
    """
    assert DECLARED_EGRESS["stage"] == TASK_KIND
    assert DECLARED_EGRESS["raw_class_egress"] is False
    assert DECLARED_EGRESS["destinations"] == ("host_local_vision_model",)

    route = resolve_derivation_route()
    assert route.task_kind == TASK_KIND
    assert route.paid_eligible is False
    assert route.tier == "local"

    # No paid route is reachable for this always-on task kind: declaring one
    # in the census fails the compile rather than opening an egress path.
    census = load_provider_census()
    paid = next(provider for provider in census.providers if provider.tier == "paid")
    paid.paid_eligible_task_kinds = [*paid.paid_eligible_task_kinds, TASK_KIND]
    with pytest.raises(PaidRouteRejectedError):
        resolve_derivation_route(census=census)

    # The owner-facing stage doc states the same posture (AC6 doc writeback).
    doc = read_doc(_STAGE_DOC)
    assert "zero raw egress" in doc


def test_declared_egress_matches_the_stage_module_posture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Completeness: the declaration is enforced against the actual destination.

    `raw_class_egress: False` is only true if the endpoint the stage would
    write a decrypted frame to is provably on this host. A census entry names a
    provider; it cannot name a socket. This asserts the second check exists and
    fails closed, so the constant is backed by enforcement rather than intent.
    """
    census = load_provider_census()
    assert census.provider(screen_derivation.LOCAL_VISION_PROVIDER).tier == "local"
    assert DECLARED_EGRESS["raw_classes"] == ("screen_frame",)

    for variable in ("OLLAMA_HOST", "OLLAMA_URL"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv(screen_derivation.HOST_LOCAL_VISION_ALLOWLIST_ENV, raising=False)

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    assert screen_derivation.resolve_local_vision_endpoint() == "http://localhost:11434"

    monkeypatch.setenv("OLLAMA_BASE_URL", "https://vision.example.com")
    with pytest.raises(screen_derivation.RawEgressRefusedError):
        screen_derivation.resolve_local_vision_endpoint()
