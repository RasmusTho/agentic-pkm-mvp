"""Contract tests for the authority-aware devUI discovery projection (#4985)."""

from __future__ import annotations

from app.builderops.devui_discovery import compose_discovery_projection


NOW = "2026-08-25T12:00:00+00:00"


def _ref(source_id: str) -> dict[str, str]:
    return {
        "source_type": "github_issue",
        "source_id": source_id,
        "version": "updated-at:2026-08-25T12:00:00+00:00",
        "locator": f"https://example.test/{source_id}",
    }


def _composition() -> dict:
    return {
        "contract_version": "devui.composition.v1",
        "authority": "projection_only",
        "captured_at": NOW,
        "providers": {
            "work": {
                "provider": "builderops_cockpit",
                "status": "available",
                "authority": "read_time_join",
                "captured_at": NOW,
                "snapshot": {"watermark": "work:42"},
                "completeness": {"claim": {"kind": "counted"}},
            }
        },
    }


def _item() -> dict:
    return {
        "source_ref": _ref("4985"),
        "source_role": "working",
        "authority_class": "non-normative",
        "artifact_class": "proposal",
        "lifecycle": {"stage": "explore", "state": "draft"},
        "provenance": {
            "source_refs": [_ref("owner-doc")],
            "derived_from": [_ref("research")],
            "review_or_promotion_ref": None,
            "receipt_refs": [],
        },
        "freshness": {"observed_at": NOW, "watermark": "vault:42", "state": "fresh"},
        "limitations": ["Working material is not an accepted owner document."],
        "navigation": {
            "inspect_ref": _ref("4985"),
            "governed_route_ref": _ref("promotion-intent"),
        },
    }


def test_discovery_projection_preserves_source_authority_and_provenance() -> None:
    item = _item()

    result = compose_discovery_projection(composition=_composition(), items=[item])

    projected = result["items"][0]
    assert result["authority"] == "projection_only"
    assert projected["source_ref"] == item["source_ref"]
    assert projected["source_role"] == "working"
    assert projected["authority_class"] == "non-normative"
    assert projected["artifact_class"] == "proposal"
    assert projected["lifecycle"] == item["lifecycle"]
    assert projected["provenance"] == item["provenance"]
    assert projected["freshness"] == item["freshness"]
    assert projected["limitations"] == item["limitations"]


def test_builder_vault_items_remain_non_normative_when_projected() -> None:
    item = _item()
    item["source_ref"] = {
        **_ref("vault-draft"),
        "source_type": "builder_vault",
    }
    item["artifact_class"] = "derived"

    result = compose_discovery_projection(composition=_composition(), items=[item])

    projected = result["items"][0]
    assert projected["authority_class"] == "non-normative"
    assert projected["presentation"] == {
        "non_normative": True,
        "ephemeral_or_rebuildable": True,
    }
    assert projected["provenance"]["source_refs"] == item["provenance"]["source_refs"]


def test_discovery_withdraws_only_claims_with_degraded_source_state() -> None:
    healthy = _item()
    degraded = _item()
    degraded["source_ref"] = _ref("unread-source")
    degraded["freshness"] = {
        "observed_at": NOW,
        "watermark": None,
        "state": "unread",
    }
    degraded["limitations"] = ["The source has not been read for this composition."]

    result = compose_discovery_projection(
        composition=_composition(), items=[healthy, degraded]
    )

    assert result["items"][0]["claim_status"] == "available"
    assert result["items"][1]["claim_status"] == "withdrawn"
    assert result["items"][1]["freshness"]["state"] == "unread"
    assert result["items"][1]["limitations"] == degraded["limitations"]


def test_discovery_navigation_is_source_bound_and_read_only() -> None:
    item = _item()
    source_items = [item]

    result = compose_discovery_projection(
        composition=_composition(), items=source_items
    )

    assert result["navigation_mode"] == "source_bound_read_only"
    assert result["items"][0]["navigation"] == item["navigation"]
    assert result["items"] is not source_items
    source_items[0]["limitations"].append("mutation after composition")
    assert "mutation after composition" not in result["items"][0]["limitations"]
