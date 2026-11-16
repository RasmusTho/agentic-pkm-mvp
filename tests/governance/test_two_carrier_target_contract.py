"""Keep the prospective carrier contract behind today's protected path."""

from pathlib import Path

import pytest

from app.builderops.control_plane.issue_delivery import manifest_hash
from app.builderops.execution_routing import (
    ResolvedExecutionTarget,
    get_carrier_adapter,
    resolve_execution_target_for_intent,
)
from app.builderops.issue_delivery_operation import (
    IssueDeliveryOperationAdapter,
    IssueDeliveryOperationRefused,
)
from app.components.settings.providers_loader import load_provider_census
from tests.builderops.test_control_plane_issue_delivery import _manifest


ROOT = Path(__file__).resolve().parents[2]


def _process_contract() -> str:
    text = (ROOT / "docs/development/BUILDER_SYSTEM_PROCESS_MAP.md").read_text(
        encoding="utf-8"
    )
    start = text.index("### Current active Builder carrier")
    end = text.index("### L0 root", start)
    return " ".join(text[start:end].split())


def _target() -> ResolvedExecutionTarget:
    return resolve_execution_target_for_intent(
        load_provider_census(), channel="dev", selection_intent="general_delivery"
    )


def test_two_carrier_target_preserves_current_protected_path() -> None:
    codex = get_carrier_adapter("codex")
    future = get_carrier_adapter("claude")
    assert codex.active is True
    assert codex.bind(_target(), selection_intent="general_delivery").launchable is True
    assert future.active is False
    binding = future.bind(_target(), selection_intent="general_delivery")
    assert binding.launchable is False
    assert binding.provider is None and binding.model is None

    # The real Issue operation refuses an unprepared carrier even with an admitted-shaped
    # manifest; the dormant routing adapter cannot substitute for the protected worker.
    approval = _manifest(operation_key="two-carrier-governance-test")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    with pytest.raises(IssueDeliveryOperationRefused, match="prepared content-only launcher"):
        IssueDeliveryOperationAdapter(
            approval,
            client=object(),
            launcher=future,
            require_protected_composition=True,
        )

    contract = _process_contract()
    for boundary in (
        "Codex is the only active Builder worker carrier",
        "authenticated owner-admission and immutable approval",
        "frozen one-Issue plan/hash",
        "IssueDeliveryOperationAdapter",
        "protected host executor",
        "scoped effect gates and authenticated source readback",
        "cannot authorize a second attempt or a different carrier",
    ):
        assert boundary in contract


def test_two_carrier_target_keeps_activation_separate() -> None:
    contract = _process_contract()
    for requirement in (
        "isolated CLI/session experiments do not qualify a carrier",
        "bounded dormant adapter",
        "prove Linux isolation and protected effect boundaries",
        "qualify the actual host, executable, profile and live operation",
        "Real owner controls require their own proved semantics and acceptance",
        "a real owner trial and outcome remain separate",
        "No stage alone implicitly authorizes the next",
        "stop or pause as unsupported unless",
    ):
        assert requirement in contract

    for name in (
        "docs/development/BUILDER_SUBAGENT_ROLES.md",
        ".codex/skills/README.md",
    ):
        text = " ".join((ROOT / name).read_text(encoding="utf-8").split())
        assert "CURRENT ACTIVE BUILDER CARRIER" in text.upper()
        assert "compatibility" in text.lower()
        assert "qualification" in text.lower()
