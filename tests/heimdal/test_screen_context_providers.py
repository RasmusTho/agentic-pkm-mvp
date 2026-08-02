"""SCREEN-02 local context providers are pluggable (#3344).

AC5. The frontmost-app/window provider is provider #1; others (active
calendar event, the frontmost editor's git branch, playing media) plug in as
declared providers. Adding one must change the derived summary/mentions
*without* changing the observation contract or the derivation entrypoint
signature.
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, List

import pytest

from app.events.topic_schema_registry import validate_topic_payload
from app.heimdal.observation_log import read_observations_from
from app.heimdal.screen_context_providers import (
    FRONTMOST_APP_PROVIDER,
    ContextContribution,
    FrameContext,
    register_context_provider,
    registered_context_providers,
    unregister_context_provider,
)
from app.heimdal.screen_derivation import (
    ContextDimensionConflictError,
    derive_activity_observations,
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


def _git_branch_provider(context: FrameContext) -> ContextContribution:
    """A second local provider: the frontmost editor's checked-out branch."""
    branch = str(context.bundle.get("git_branch") or "feature/ere")
    return ContextContribution(
        provider="git_branch",
        facts=(f"git branch: {branch}",),
        mentions=({"surface_form": branch, "kind_hint": "git_branch"},),
    )


def _payload() -> Dict[str, Any]:
    rows = read_observations_from(0)
    return dict(rows[-1].envelope["payload"])


def test_provider_registry_extensible() -> None:
    """Success path: a new provider changes the derived text and mentions.

    Completeness path: the derivation entrypoint signature and the published
    observation contract are byte-for-byte unchanged by the added provider,
    and the registry refuses a duplicate or non-callable registration.
    """
    baseline_signature = inspect.signature(derive_activity_observations)
    assert [name for name, _ in registered_context_providers()] == [FRONTMOST_APP_PROVIDER]

    first = land_frame(frame="providers-1", observed_at="2026-07-11T13:00:00Z")
    derive_activity_observations(
        [first],
        episode_id="screen-session-providers",
        vision_runner=stub_vision_runner(),
        key=RAW_STORE_KEY,
    )
    before = _payload()
    assert "git branch" not in str(before["content"])
    assert all(m["kind_hint"] != "git_branch" for m in before["entity_mentions"])

    # --- add a provider; same entrypoint call, richer derived observation
    register_context_provider("git_branch", _git_branch_provider)
    assert [name for name, _ in registered_context_providers()] == [
        FRONTMOST_APP_PROVIDER,
        "git_branch",
    ]

    second = land_frame(frame="providers-2", observed_at="2026-07-11T13:01:00Z")
    derive_activity_observations(
        [second],
        episode_id="screen-session-providers",
        vision_runner=stub_vision_runner(),
        key=RAW_STORE_KEY,
    )
    after = _payload()

    assert "git branch: feature/ere" in str(after["content"])
    assert any(m["kind_hint"] == "git_branch" for m in after["entity_mentions"])
    assert any(m["surface_form"] == "feature/ere" for m in after["entity_mentions"])

    # --- contract unchanged: same entrypoint signature, same payload shape
    assert inspect.signature(derive_activity_observations) == baseline_signature
    assert set(after) == set(before)
    validate_topic_payload("heimdal.observation.published", after)

    # --- registry refuses ambiguous or unusable registrations
    with pytest.raises(ValueError, match="already registered"):
        register_context_provider("git_branch", _git_branch_provider)
    with pytest.raises(TypeError):
        register_context_provider("not_callable", "nope")  # type: ignore[arg-type]

    unregister_context_provider("git_branch")
    assert [name for name, _ in registered_context_providers()] == [FRONTMOST_APP_PROVIDER]


def test_two_providers_cannot_claim_one_segmenter_dimension() -> None:
    """A provider must not silently overwrite another's span dimension.

    Last-writer-wins on `app`/`window`/`scope` would let a second provider move
    a span boundary invisibly (INV-SCREEN-E, the unrecoverable direction), so
    the collision is refused at derivation time rather than resolved by
    registration order.
    """

    def shadow_provider(context: FrameContext) -> ContextContribution:
        return ContextContribution(provider="shadow", dimensions={"app": "CONSTANT"})

    register_context_provider("shadow", shadow_provider)
    frame = land_frame(frame="providers-conflict", observed_at="2026-07-11T13:03:00Z")
    with pytest.raises(ContextDimensionConflictError, match="app"):
        derive_activity_observations(
            [frame],
            episode_id="screen-session-providers",
            vision_runner=stub_vision_runner(),
            key=RAW_STORE_KEY,
        )


def test_frontmost_app_provider_supplies_the_segmenter_dimensions() -> None:
    """Provider #1 is what feeds the app/window/scope coalescing dimensions."""
    frame = land_frame(
        frame="providers-dimensions",
        observed_at="2026-07-11T13:02:00Z",
        app="Safari",
        window="PR #3185",
        scope="work",
    )
    requests: List[Any] = []

    def runner(request: Any) -> Dict[str, Any]:
        requests.append(request)
        return {"summary": "Reviewing a pull request", "goal": "review", "confidence": 0.5}

    derive_activity_observations(
        [frame],
        episode_id="screen-session-providers",
        vision_runner=runner,
        key=RAW_STORE_KEY,
    )
    assert requests
    dimensions = dict(requests[0].dimensions)
    assert dimensions["app"] == "Safari"
    assert dimensions["window"] == "PR #3185"
    assert dimensions["scope"] == "work"
