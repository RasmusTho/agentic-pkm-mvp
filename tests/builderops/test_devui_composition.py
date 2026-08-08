"""Contract tests for the read-only devUI provider composition (#4682)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.builderops.devui_composition import compose_owner_snapshot


NOW = datetime(2026, 8, 8, 21, 0, tzinfo=timezone.utc)


def _cockpit_payload() -> dict:
    return {
        "authority": "read_time_join",
        "generated_at": "2026-08-08T20:59:58+00:00",
        "claim": {"kind": "counted", "text": "2 threads in motion."},
        "sources": [
            {
                "name": "dispatcher-store",
                "state": "fresh",
                "read_at": "2026-08-08T20:59:58+00:00",
            }
        ],
        "unread_planes": ["github-review-threads"],
        "withdrawn_counts": [],
        "bands": {"moving": [{"issue_number": 4682}]},
    }


def _ckm_payload() -> dict:
    return {
        "schema_version": 1,
        "resource_type": "capability",
        "query_digest": "query-digest",
        "projection": {"status": "derived_projection", "authoritative": False},
        "snapshot": {
            "epoch": "epoch-7",
            "state_revision": 42,
            "snapshot_digest": "snapshot-digest",
            "watermarks": {"capability": "2026-08-08T20:58:00+00:00"},
            "completeness": {
                "complete": True,
                "object_classes": [
                    {
                        "object_class": "capability",
                        "included": 1,
                        "filtered": 0,
                        "omitted": 0,
                        "truncated": 0,
                    }
                ],
            },
        },
        "resources": [{"public_id": "ckm_capability_example"}],
    }


def test_composition_preserves_provider_snapshot_and_authority() -> None:
    cockpit = _cockpit_payload()
    ckm = _ckm_payload()

    result = compose_owner_snapshot(
        cockpit_reader=lambda: cockpit,
        ckm_reader=lambda: ckm,
        now=lambda: NOW,
    )

    assert result["contract_version"] == "devui.composition.v1"
    assert result["authority"] == "projection_only"
    assert result["captured_at"] == "2026-08-08T21:00:00+00:00"

    work = result["providers"]["work"]
    assert work["status"] == "available"
    assert work["authority"] == cockpit["authority"]
    assert work["captured_at"] == cockpit["generated_at"]
    assert work["snapshot"] == {
        "generated_at": cockpit["generated_at"],
        "sources": cockpit["sources"],
    }
    assert work["completeness"] == {
        "claim": cockpit["claim"],
        "unread_planes": cockpit["unread_planes"],
        "withdrawn_counts": cockpit["withdrawn_counts"],
    }
    assert work["payload"] is cockpit

    capabilities = result["providers"]["capabilities"]
    assert capabilities["status"] == "available"
    assert capabilities["authority"] == ckm["projection"]
    assert capabilities["captured_at"] is None
    assert capabilities["snapshot"] is ckm["snapshot"]
    assert capabilities["completeness"] is ckm["snapshot"]["completeness"]
    assert capabilities["payload"] is ckm


def test_composition_uses_existing_read_only_provider_contracts() -> None:
    reads: list[str] = []

    def read_cockpit() -> dict:
        reads.append("cockpit")
        return _cockpit_payload()

    class CkmEnvelope:
        def to_dict(self) -> dict:
            reads.append("ckm")
            return _ckm_payload()

    result = compose_owner_snapshot(
        cockpit_reader=read_cockpit,
        ckm_reader=CkmEnvelope,
        now=lambda: NOW,
    )

    assert reads == ["cockpit", "ckm"]
    assert result["providers"]["work"]["provider"] == "builderops_cockpit"
    assert result["providers"]["capabilities"]["provider"] == "ckm"


def test_provider_failure_is_isolated_and_never_rendered_as_zero() -> None:
    def broken_cockpit() -> dict:
        raise OSError("secret path: /private/dispatcher.sqlite3")

    result = compose_owner_snapshot(
        cockpit_reader=broken_cockpit,
        ckm_reader=lambda: _ckm_payload(),
        now=lambda: NOW,
    )

    work = result["providers"]["work"]
    assert work == {
        "provider": "builderops_cockpit",
        "status": "refused",
        "authority": "read_time_join",
        "captured_at": None,
        "snapshot": None,
        "completeness": None,
        "refusal": {
            "code": "provider_unavailable",
            "message": "BuilderOps Cockpit could not provide its read snapshot",
            "details": {"reason": "provider read failed"},
        },
    }
    assert "payload" not in work
    assert "/private/dispatcher.sqlite3" not in repr(work)
    assert result["providers"]["capabilities"]["status"] == "available"
    assert result["providers"]["capabilities"]["payload"]["resources"]

    refused_ckm = compose_owner_snapshot(
        cockpit_reader=lambda: _cockpit_payload(),
        ckm_reader=lambda: {
            "schema_version": 1,
            "error": {
                "code": "missing_store",
                "message": "CKM database does not exist",
                "details": {"path": "/unavailable/ckm.sqlite3"},
            },
        },
        now=lambda: NOW,
    )["providers"]["capabilities"]

    assert refused_ckm["status"] == "refused"
    assert refused_ckm["refusal"] == {
        "code": "missing_store",
        "message": "CKM refused the read request",
        "details": {},
    }
    assert "/unavailable/ckm.sqlite3" not in repr(refused_ckm)
    assert "payload" not in refused_ckm
