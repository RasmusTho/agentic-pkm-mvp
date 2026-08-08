"""Contract tests for the read-only devUI provider composition (#4682)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.builderops.ckm.contracts import (
    CkmContractError,
    CkmStateIdentity,
    CompletenessManifest,
    ErrorEnvelope,
    ObjectClassCompleteness,
    ResourceDto,
    ResultEnvelope,
    SnapshotManifest,
    canonical_digest,
    canonical_query_digest,
)
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


def _ckm_envelope() -> ResultEnvelope:
    resource = ResourceDto(
        public_id="ckm_capability_example",
        resource_type="capability",
        display_name="Example capability",
        lifecycle="confirmed",
        provenance=({"kind": "fixture"},),
        values={},
        candidate=False,
    )
    completeness = CompletenessManifest(
        object_classes=(
            ObjectClassCompleteness(object_class="capability", included=1),
        ),
        complete=True,
    )
    snapshot = SnapshotManifest.build(
        state=CkmStateIdentity(epoch="epoch-7", state_revision=42),
        taxonomy_digest=canonical_digest({"taxonomy": "fixture"}),
        watermarks={"capability": "2026-08-08T20:58:00+00:00"},
        provenance=({"kind": "fixture"},),
        completeness=completeness,
        read_set={"capability": (resource.public_id,)},
    )
    return ResultEnvelope(
        resource_type="capability",
        query_digest=canonical_query_digest(
            {"operation": "list_capabilities", "public_id": None}
        ),
        snapshot=snapshot,
        resources=(resource,),
    )


def test_composition_preserves_provider_snapshot_and_authority() -> None:
    cockpit = _cockpit_payload()
    ckm_envelope = _ckm_envelope()
    ckm = ckm_envelope.to_dict()

    result = compose_owner_snapshot(
        cockpit_reader=lambda: cockpit,
        ckm_reader=lambda: ckm_envelope,
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
    assert work["payload"] == cockpit

    capabilities = result["providers"]["capabilities"]
    assert capabilities["status"] == "available"
    assert capabilities["authority"] == ckm["projection"]
    assert capabilities["captured_at"] is None
    assert capabilities["snapshot"] == ckm["snapshot"]
    assert capabilities["completeness"] == ckm["snapshot"]["completeness"]
    assert capabilities["payload"] == ckm


def test_composition_uses_existing_read_only_provider_contracts() -> None:
    reads: list[str] = []

    def read_cockpit() -> dict:
        reads.append("cockpit")
        return _cockpit_payload()

    def read_ckm() -> ResultEnvelope:
        reads.append("ckm")
        return _ckm_envelope()

    result = compose_owner_snapshot(
        cockpit_reader=read_cockpit,
        ckm_reader=read_ckm,
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
        ckm_reader=_ckm_envelope,
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
        ckm_reader=lambda: ErrorEnvelope(
            CkmContractError(
                code="missing_store",
                message="CKM database does not exist",
                details={"path": "/unavailable/ckm.sqlite3"},
            )
        ),
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


def test_unserializable_cockpit_payload_is_isolated_from_healthy_ckm() -> None:
    malformed_cockpit = _cockpit_payload()
    malformed_cockpit["bands"] = {"moving": object()}

    result = compose_owner_snapshot(
        cockpit_reader=lambda: malformed_cockpit,
        ckm_reader=_ckm_envelope,
        now=lambda: NOW,
    )

    assert result["providers"]["work"]["status"] == "refused"
    assert result["providers"]["work"]["snapshot"] is None
    assert result["providers"]["capabilities"]["status"] == "available"


@pytest.mark.parametrize(
    "unsupported_envelope",
    [
        replace(_ckm_envelope(), schema_version=999),
        replace(
            _ckm_envelope(),
            snapshot=replace(
                _ckm_envelope().snapshot,
                envelope_schema_version=999,
            ),
        ),
        replace(
            _ckm_envelope(),
            resources=(replace(_ckm_envelope().resources[0], schema_version=999),),
        ),
        ErrorEnvelope(
            CkmContractError(code="missing_store", message="missing", details={}),
            schema_version=999,
        ),
    ],
)
def test_unsupported_typed_ckm_versions_are_refused(
    unsupported_envelope: ResultEnvelope | ErrorEnvelope,
) -> None:
    contribution = compose_owner_snapshot(
        cockpit_reader=_cockpit_payload,
        ckm_reader=lambda: unsupported_envelope,
        now=lambda: NOW,
    )["providers"]["capabilities"]

    assert contribution["status"] == "refused"
    assert contribution["snapshot"] is None
    assert contribution["refusal"]["code"] == "provider_unavailable"
    assert "payload" not in contribution


@pytest.mark.parametrize(
    "unvalidated_payload",
    [
        {"snapshot": {"completeness": {}}},
        {
            "contract_version": True,
            "schema_version": True,
            "snapshot": {"completeness": {"complete": True}},
        },
        {
            "snapshot": {
                "snapshot_digest": "forged",
                "read_set_digest": "forged",
                "completeness": {"complete": True},
            },
            "resources": [],
        },
        {
            "snapshot": {
                "completeness": {
                    "complete": True,
                    "object_classes": [
                        {"object_class": "capability", "included": 0},
                        {"object_class": "capability", "included": 0},
                    ],
                }
            },
            "resources": [],
        },
    ],
)
def test_unvalidated_ckm_mapping_is_refused(
    unvalidated_payload: dict,
) -> None:
    contribution = compose_owner_snapshot(
        cockpit_reader=lambda: _cockpit_payload(),
        ckm_reader=lambda: unvalidated_payload,  # type: ignore[return-value]
        now=lambda: NOW,
    )["providers"]["capabilities"]

    assert contribution["status"] == "refused"
    assert contribution["snapshot"] is None
    assert contribution["refusal"] == {
        "code": "provider_unavailable",
        "message": "CKM could not provide its read snapshot",
        "details": {"reason": "provider read failed"},
    }
    assert "payload" not in contribution
