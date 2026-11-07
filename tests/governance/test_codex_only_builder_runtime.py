from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.builderops import issue_delivery_effect_executor as executor
from app.builderops.control_plane.client import BuilderOpsControlPlaneClient
from app.builderops.epic_dispatch import build_dispatch_plan
from app.builderops.execution_routing import get_carrier_adapter
from tests.builderops.test_epic_dispatch import _candidate


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_active_builder_runtime_is_codex_only(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = build_dispatch_plan(
        epic_issue_number=3229,
        run_id="governance-carrier-default",
        candidates=[_candidate(3001, risk="high", files=["app/example.py"])],
    )
    assert plan["runtime_targets"] == ["codex"]
    assert plan["context_packs"][0]["runtime"]["carrier"] == "codex"
    assert get_carrier_adapter("codex").active is True
    assert get_carrier_adapter("claude").active is False

    # A dormant implementation is not host qualification: default production
    # composition refuses without its independently installed verifier.
    monkeypatch.setattr(executor, "_HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME", None)
    approval = {"contract_version": "fca-issue-delivery.v4", "operation_key": "operation"}
    client = object.__new__(BuilderOpsControlPlaneClient)
    monkeypatch.setattr(client, "issue_delivery_authority", lambda **_: {
        "approval": approval, "purpose": "execute", "operation_key": "operation", "authority_epoch": 1,
    })
    preparations = []
    destination = SimpleNamespace(prepare=lambda value: preparations.append(value))
    with pytest.raises(ValueError, match="verifier is unavailable"):
        executor.PreparedIssueDeliveryWorker.create(
            approval=approval, destination=destination, authority_client=client, launcher_factory=lambda _: None,
        )
    assert preparations == []

    process_map = (REPO_ROOT / "docs/development/BUILDER_SYSTEM_PROCESS_MAP.md").read_text(encoding="utf-8")
    assert "### Current active Builder carrier" in process_map
    assert "Codex is the only active Builder worker carrier" in process_map
