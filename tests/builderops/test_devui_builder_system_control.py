"""Hostile contract tests for the BSC-01 governing-document projection."""

from __future__ import annotations

from copy import deepcopy
import inspect

import pytest

from app.builderops.devui_builder_system_control import (
    GoverningDocumentContractError,
    compose_governing_document_inventory,
)


def _ref(source_id: str) -> dict[str, str]:
    return {
        "source_type": "repository_document",
        "source_id": source_id,
        "version": "git:315d8103",
        "locator": source_id,
    }


def _state(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "availability": "available",
        "freshness": "fresh",
        "coverage": "complete",
        "cardinality": "nonempty",
        "linkage": "linked",
        "captured_at": "2026-08-10T08:00:00+00:00",
        "fresh_until": "2026-08-11T08:00:00+00:00",
        "read_scope": "document:declared-governing-document",
        "read_watermark": "git:315d8103",
        "limitations": [],
    }
    value.update(overrides)
    return value


def _document(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "source_ref": _ref("docs/architecture/SBS_OPERATING_MODEL.md"),
        "role": "Builder System operating model",
        "authority_class": "normative",
        "authority_scope": "Builder System boundary and work classification",
        "owner_ref": _ref("docs/architecture/SBS_OPERATING_MODEL.md#owner"),
        "lifecycle": {
            "phase": "accepted",
            "temporal_class": "strategic",
            "review_cadence": "event-driven",
            "supersedes_refs": [],
            "superseded_by_refs": [],
        },
        "source_state": _state(),
        "limitations": [],
    }
    value.update(overrides)
    return value


def _compose(*documents: dict[str, object]) -> dict[str, object]:
    return compose_governing_document_inventory(
        repository_ref="RasmusTho/agentic-pkm-mvp",
        governance_baseline_ref=_ref("docs/architecture/SBS_OPERATING_MODEL.md"),
        composed_at="2026-08-10T08:01:00+00:00",
        declarations=list(documents),
        limitations=[],
    )


def test_governing_document_inventory_is_projection_only_and_has_no_io_or_state_path() -> None:
    result = _compose(_document())

    assert result == {
        "contract_version": "builder-system-control-view.v1",
        "authority": "projection_only",
        "primary_identity": "builder_system",
        "scope": {
            "kind": "builder_system",
            "repository_ref": "RasmusTho/agentic-pkm-mvp",
            "governance_baseline_ref": _ref("docs/architecture/SBS_OPERATING_MODEL.md"),
        },
        "composed_at": "2026-08-10T08:01:00+00:00",
        "governing_documents": [_document()],
        "limitations": [],
    }
    source = inspect.getsource(compose_governing_document_inventory)
    assert "open(" not in source
    assert "Path(" not in source
    assert "requests" not in source


def test_governing_document_inventory_preserves_declared_authority_and_lifecycle() -> None:
    document = _document()
    result = _compose(document)

    rendered = result["governing_documents"][0]
    assert rendered["source_ref"] == document["source_ref"]
    assert rendered["role"] == document["role"]
    assert rendered["authority_class"] == "normative"
    assert rendered["authority_scope"] == document["authority_scope"]
    assert rendered["owner_ref"] == document["owner_ref"]
    assert rendered["lifecycle"] == document["lifecycle"]
    assert rendered["source_state"] == document["source_state"]
    assert rendered["limitations"] == []


def test_governing_document_inventory_never_infers_missing_authority_or_lifecycle() -> None:
    missing = _document(
        owner_ref=None,
        lifecycle=None,
        source_state=_state(
            coverage="missing",
            cardinality="not_measured",
            linkage="unlinked",
        ),
    )
    result = _compose(missing)
    rendered = result["governing_documents"][0]

    assert rendered["owner_ref"] is None
    assert rendered["lifecycle"] == {
        "phase": "unknown",
        "temporal_class": "unknown",
        "review_cadence": "unknown",
        "supersedes_refs": [],
        "superseded_by_refs": [],
    }
    assert rendered["source_state"]["coverage"] == "missing"
    assert rendered["source_state"]["linkage"] == "unlinked"

    conflicting = deepcopy(missing)
    conflicting["source_state"] = _state()
    with pytest.raises(GoverningDocumentContractError, match="missing owner"):
        _compose(conflicting)


def test_governing_document_inventory_preserves_independent_source_axes() -> None:
    unavailable = _document(
        source_state=_state(
            availability="unavailable",
            freshness="fresh",
            coverage="unread",
            cardinality="not_measured",
            linkage="not_assessed",
        )
    )
    unread = _document(
        source_ref=_ref("docs/DEVUI.md"),
        source_state=_state(
            availability="available",
            freshness="stale",
            coverage="unread",
            cardinality="not_measured",
            linkage="unlinked",
        ),
    )
    measured_empty = _document(
        source_ref=_ref("docs/empty.md"),
        source_state=_state(cardinality="measured_empty"),
    )
    result = _compose(unavailable, unread, measured_empty)

    rendered = result["governing_documents"]
    assert rendered[0]["source_state"] == unavailable["source_state"]
    assert rendered[1]["source_state"] == unread["source_state"]
    assert rendered[2]["source_state"] == measured_empty["source_state"]

    hostile_empty = deepcopy(measured_empty)
    hostile_empty["source_state"] = _state(
        availability="unavailable",
        cardinality="measured_empty",
    )
    with pytest.raises(GoverningDocumentContractError, match="measured_empty"):
        _compose(hostile_empty)
