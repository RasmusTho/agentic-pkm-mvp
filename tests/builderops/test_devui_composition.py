"""Contract tests for the read-only devUI provider composition (#4682)."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
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
    TaggedValue,
    canonical_digest,
    canonical_query_digest,
)
from app.builderops.devui_composition import compose_owner_snapshot


NOW = datetime(2026, 8, 8, 21, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _FakeProjection:
    status: str = "derived_projection"
    authoritative: bool = False
    leaked: str = "/private/authority-secret"


@dataclass(frozen=True)
class _FakeError:
    code: str = "missing_store"
    message: str = "forged"
    details: dict | None = None



def _cockpit_payload() -> dict:
    return {
        "authority": "read_time_join",
        "generated_at": "2026-08-08T20:59:58+00:00",
        "claim": {
            "kind": "counted",
            "text": "2 threads in motion.",
            "as_of": "2026-08-08T20:59:58+00:00",
        },
        "sources": [
            {
                "name": "dispatcher-store",
                "state": "fresh",
                "last_successful_read": "2026-08-08T20:59:58+00:00",
                "detail": "read succeeded",
                "stale_after_days": 7,
                "configured": True,
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


def _rebuilt_ckm_envelope(
    *,
    epoch: str = "epoch-7",
    state_revision: int = 42,
    taxonomy_digest: str | None = None,
    completeness: CompletenessManifest | None = None,
    watermarks: dict | None = None,
    provenance: tuple[dict, ...] | None = None,
    resource: ResourceDto | None = None,
) -> ResultEnvelope:
    original = _ckm_envelope()
    selected_resource = resource or original.resources[0]
    rebuilt_snapshot = SnapshotManifest.build(
        state=CkmStateIdentity(epoch=epoch, state_revision=state_revision),
        taxonomy_digest=taxonomy_digest or canonical_digest({"taxonomy": "fixture"}),
        watermarks=watermarks if watermarks is not None else original.snapshot.watermarks,
        provenance=provenance if provenance is not None else original.snapshot.provenance,
        completeness=completeness or original.snapshot.completeness,
        read_set={"capability": (selected_resource.public_id,)},
    )
    return ResultEnvelope(
        resource_type=original.resource_type,
        query_digest=original.query_digest,
        snapshot=rebuilt_snapshot,
        resources=(selected_resource,),
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


def test_semantically_malformed_cockpit_payload_is_isolated() -> None:
    malformed_cockpit = _cockpit_payload()
    malformed_cockpit.update(
        {
            "generated_at": "not-a-timestamp",
            "claim": {"kind": "counted", "text": 7},
            "sources": [None],
            "unread_planes": [7],
            "withdrawn_counts": [{"source": 7, "counts": [None]}],
        }
    )

    result = compose_owner_snapshot(
        cockpit_reader=lambda: malformed_cockpit,
        ckm_reader=_ckm_envelope,
        now=lambda: NOW,
    )

    assert result["providers"]["work"]["status"] == "refused"
    assert result["providers"]["work"]["captured_at"] is None
    assert result["providers"]["capabilities"]["status"] == "available"


def test_contradictory_cockpit_evidence_is_refused() -> None:
    variants: list[dict] = []

    missing_as_of = deepcopy(_cockpit_payload())
    del missing_as_of["claim"]["as_of"]
    variants.append(missing_as_of)

    mismatched_as_of = deepcopy(_cockpit_payload())
    mismatched_as_of["claim"]["as_of"] = "2025-01-01T00:00:00+00:00"
    variants.append(mismatched_as_of)

    missing_read_time = deepcopy(_cockpit_payload())
    missing_read_time["sources"][0]["last_successful_read"] = None
    variants.append(missing_read_time)

    unconfigured_fresh = deepcopy(_cockpit_payload())
    unconfigured_fresh["sources"][0]["configured"] = False
    variants.append(unconfigured_fresh)

    duplicate_source = deepcopy(_cockpit_payload())
    duplicate_source["sources"].append(deepcopy(duplicate_source["sources"][0]))
    variants.append(duplicate_source)

    orphaned_withdrawal = deepcopy(_cockpit_payload())
    orphaned_withdrawal["withdrawn_counts"] = [
        {"source": "missing-source", "counts": []}
    ]
    variants.append(orphaned_withdrawal)

    counted_unavailable = deepcopy(_cockpit_payload())
    counted_unavailable["sources"][0].update(
        {"state": "unavailable", "last_successful_read": None}
    )
    variants.append(counted_unavailable)

    refused_fresh = deepcopy(_cockpit_payload())
    refused_fresh["claim"]["kind"] = "refused"
    variants.append(refused_fresh)

    missing_dispatcher = deepcopy(_cockpit_payload())
    missing_dispatcher["sources"] = []
    variants.append(missing_dispatcher)

    for payload in variants:
        result = compose_owner_snapshot(
            cockpit_reader=lambda payload=payload: payload,
            ckm_reader=_ckm_envelope,
            now=lambda: NOW,
        )
        assert result["providers"]["work"]["status"] == "refused"
        assert result["providers"]["capabilities"]["status"] == "available"


@pytest.mark.parametrize(
    "unsupported_envelope",
    [
        replace(_ckm_envelope(), schema_version=999),
        replace(_ckm_envelope(), schema_version=True),
        replace(_ckm_envelope(), schema_version=1.0),
        replace(
            _ckm_envelope(),
            snapshot=replace(
                _ckm_envelope().snapshot,
                envelope_schema_version=999,
            ),
        ),
        replace(
            _ckm_envelope(),
            snapshot=replace(
                _ckm_envelope().snapshot,
                ckm_schema_version=5.0,
            ),
        ),
        replace(
            _ckm_envelope(),
            snapshot=replace(
                _ckm_envelope().snapshot,
                envelope_schema_version=True,
            ),
        ),
        replace(
            _ckm_envelope(),
            snapshot=replace(
                _ckm_envelope().snapshot,
                resource_schema_version=True,
            ),
        ),
        replace(
            _ckm_envelope(),
            resources=(replace(_ckm_envelope().resources[0], schema_version=999),),
        ),
        replace(
            _ckm_envelope(),
            resources=(replace(_ckm_envelope().resources[0], schema_version=True),),
        ),
        ErrorEnvelope(
            CkmContractError(code="missing_store", message="missing", details={}),
            schema_version=999,
        ),
        ErrorEnvelope(
            CkmContractError(code="missing_store", message="missing", details={}),
            schema_version=True,
        ),
        ErrorEnvelope(
            CkmContractError(code="missing_store", message="missing", details={}),
            schema_version=1.0,
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


def test_ckm_query_identity_must_match_list_capabilities() -> None:
    forged = replace(_ckm_envelope(), query_digest="forged")

    contribution = compose_owner_snapshot(
        cockpit_reader=_cockpit_payload,
        ckm_reader=lambda: forged,
        now=lambda: NOW,
    )["providers"]["capabilities"]

    assert contribution["status"] == "refused"
    assert contribution["snapshot"] is None
    assert contribution["refusal"]["code"] == "provider_unavailable"
    assert "payload" not in contribution


@pytest.mark.parametrize(
    "malformed_envelope",
    [
        _rebuilt_ckm_envelope(epoch=""),
        _rebuilt_ckm_envelope(state_revision=-1),
        _rebuilt_ckm_envelope(state_revision=True),
        _rebuilt_ckm_envelope(taxonomy_digest="forged"),
        _rebuilt_ckm_envelope(
            completeness=CompletenessManifest(
                object_classes=(
                    ObjectClassCompleteness(object_class="capability", included=True),
                ),
                complete=True,
            )
        ),
        _rebuilt_ckm_envelope(
            completeness=CompletenessManifest(
                object_classes=(
                    ObjectClassCompleteness(object_class="capability", included=1),
                ),
                complete=1,
            )
        ),
    ],
)
def test_malformed_typed_ckm_snapshot_scalars_are_refused(
    malformed_envelope: ResultEnvelope,
) -> None:
    contribution = compose_owner_snapshot(
        cockpit_reader=_cockpit_payload,
        ckm_reader=lambda: malformed_envelope,
        now=lambda: NOW,
    )["providers"]["capabilities"]

    assert contribution["status"] == "refused"
    assert contribution["snapshot"] is None
    assert contribution["refusal"]["code"] == "provider_unavailable"
    assert "payload" not in contribution


@pytest.mark.parametrize(
    "malformed_envelope",
    [
        _rebuilt_ckm_envelope(watermarks={1: "value"}),
        _rebuilt_ckm_envelope(watermarks={"capability": 123}),
        _rebuilt_ckm_envelope(
            resource=replace(_ckm_envelope().resources[0], public_id=123)
        ),
        _rebuilt_ckm_envelope(
            resource=replace(_ckm_envelope().resources[0], display_name=123)
        ),
        _rebuilt_ckm_envelope(
            resource=replace(_ckm_envelope().resources[0], lifecycle=123)
        ),
        _rebuilt_ckm_envelope(
            resource=replace(_ckm_envelope().resources[0], candidate=0)
        ),
        _rebuilt_ckm_envelope(provenance=({1: "fixture"},)),
        _rebuilt_ckm_envelope(
            resource=replace(
                _ckm_envelope().resources[0],
                values={1: TaggedValue.measured("x")},
            )
        ),
    ],
)
def test_malformed_typed_ckm_public_shape_is_refused(
    malformed_envelope: ResultEnvelope,
) -> None:
    contribution = compose_owner_snapshot(
        cockpit_reader=_cockpit_payload,
        ckm_reader=lambda: malformed_envelope,
        now=lambda: NOW,
    )["providers"]["capabilities"]

    assert contribution["status"] == "refused"
    assert contribution["snapshot"] is None
    assert contribution["refusal"]["code"] == "provider_unavailable"
    assert "payload" not in contribution


@pytest.mark.parametrize(
    "malformed_envelope",
    [
        replace(_ckm_envelope(), projection=_FakeProjection()),
        ErrorEnvelope(error=_FakeError(details={})),
    ],
)
def test_untyped_nested_ckm_contract_members_are_refused(
    malformed_envelope: ResultEnvelope | ErrorEnvelope,
) -> None:
    contribution = compose_owner_snapshot(
        cockpit_reader=_cockpit_payload,
        ckm_reader=lambda: malformed_envelope,
        now=lambda: NOW,
    )["providers"]["capabilities"]

    assert contribution["status"] == "refused"
    assert contribution["snapshot"] is None
    assert contribution["refusal"]["code"] == "provider_unavailable"
    assert "/private/authority-secret" not in repr(contribution)
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
