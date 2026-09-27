from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import urllib.request

import pytest

from app.model_access.macos_acceptance import (
    ReceiptValidationError,
    validate_acceptance_receipt,
)
from scripts.validate_macos_executor_acceptance_receipt import main


_CATALOG_HASH = "sha256:" + "0" * 64


def _expected_route() -> dict[str, object]:
    return {
        "route": {
            "provider": "openai",
            "model": "codex-model-fixture",
            "transport_id": "codex_cli",
            "reasoning_effort": "high",
            "capability_intent": {
                "structured_output": False,
                "native_tools": False,
                "literal_system_role_required": False,
                "max_output_tokens_required": False,
            },
        },
        "catalog_snapshot_hash": _CATALOG_HASH,
        "executor_profile": "product_codex_executor",
        "configured_path_profiles": ["ygg_vlan_primary", "tailscale_fallback"],
    }


def _passed_receipt() -> dict[str, object]:
    return {
        "receipt_type": "model_access_router.macos_executor_acceptance.v3",
        "status": "passed",
        "route": _expected_route()["route"],
        "catalog_snapshot_hash": _CATALOG_HASH,
        "executor_profile": "product_codex_executor",
        "configured_path_profiles": ["ygg_vlan_primary", "tailscale_fallback"],
        "selected_path_profile": "ygg_vlan_primary",
        "path_selection_reason": "primary_reachable",
        "path_failure_code": None,
        "backend_loopback_only": True,
        "path_authorization": [
            {
                "path_profile": "ygg_vlan_primary",
                "channel_authorized": True,
                "action_authorized": True,
            },
            {
                "path_profile": "tailscale_fallback",
                "channel_authorized": True,
                "action_authorized": True,
            },
        ],
        "same_product_channel_action_contract": True,
        "fallback_preflight": {
            "route": _expected_route()["route"],
            "attempted_path_profiles": ["ygg_vlan_primary", "tailscale_fallback"],
            "selected_path_profile": "tailscale_fallback",
            "failure_before_selection": "PATH_UNAVAILABLE",
            "preflight_status": "passed",
            "completion_dispatched": False,
        },
        "codex_cli_version": "1.2.3",
        "codex_auth_status": "authenticated",
        "required_capability_ids": ["text_generation", "system_prompt_channel"],
        "capability_observations": [
            {
                "capability_id": "text_generation",
                "status": "available",
                "freshness": "fresh",
            },
            {
                "capability_id": "system_prompt_channel",
                "status": "available",
                "freshness": "fresh",
            },
            {
                "capability_id": "native_tools",
                "status": "unavailable",
                "freshness": "fresh",
            },
        ],
        "unsupported_capability_rejected_pre_inference": True,
        "unsupported_capability_error_code": "native_tools_unavailable",
        "instruction_channel_mapping_id": "codex_developer_instructions_user_prompt_v1",
        "ambiguous_completion_no_retry": True,
        "completion_dispatched": True,
        "missing_prerequisites": [],
    }


def test_acceptance_receipt_is_route_bound_and_secret_free(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    expected = _expected_route()
    receipt = _passed_receipt()

    result = validate_acceptance_receipt(json.dumps(receipt), json.dumps(expected))

    assert result.status == "passed"
    assert result.missing_prerequisites == ()

    changed_route = _passed_receipt()
    changed_route_identity = {
        **_expected_route()["route"],  # type: ignore[arg-type]
        "model": "gpt-6-sol",
    }
    changed_route["route"] = changed_route_identity
    changed_route["fallback_preflight"] = {
        **_passed_receipt()["fallback_preflight"],  # type: ignore[arg-type]
        "route": changed_route_identity,
    }
    with pytest.raises(ReceiptValidationError, match="route_mismatch"):
        validate_acceptance_receipt(json.dumps(changed_route), json.dumps(expected))

    changed_catalog = _passed_receipt()
    changed_catalog["catalog_snapshot_hash"] = "sha256:" + "1" * 64
    with pytest.raises(ReceiptValidationError, match="route_mismatch"):
        validate_acceptance_receipt(json.dumps(changed_catalog), json.dumps(expected))

    missing_fallback_evidence = _passed_receipt()
    missing_fallback_evidence.pop("fallback_preflight")
    with pytest.raises(ReceiptValidationError, match="receipt_invalid"):
        validate_acceptance_receipt(json.dumps(missing_fallback_evidence), json.dumps(expected))

    secret_field = _passed_receipt()
    secret_field["api_key"] = "sk-ant-do-not-print-this-value"
    receipt_path = tmp_path / "receipt.json"
    expected_path = tmp_path / "expected-route.json"
    receipt_path.write_text(json.dumps(secret_field), encoding="utf-8")
    expected_path.write_text(json.dumps(expected), encoding="utf-8")

    assert main(["--input", str(receipt_path), "--expected-route", str(expected_path)]) == 2
    output = capsys.readouterr().out
    assert output == "receipt_invalid\n"
    assert "do-not-print-this-value" not in output

    endpoint_model = _passed_receipt()
    endpoint_model["route"] = {
        **_expected_route()["route"],  # type: ignore[arg-type]
        "model": "https://private.example/model",
    }
    with pytest.raises(ReceiptValidationError, match="receipt_invalid"):
        validate_acceptance_receipt(json.dumps(endpoint_model), json.dumps(expected))


def test_duplicate_json_keys_cannot_hide_unsafe_receipt_or_route_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    expected = _expected_route()
    valid_receipt = json.dumps(_passed_receipt())
    unsafe_receipt = valid_receipt.replace(
        '"codex_cli_version": "1.2.3"',
        ('"codex_cli_version": "sk-ant-do-not-print-this-value", ' '"codex_cli_version": "1.2.3"'),
        1,
    )
    assert unsafe_receipt != valid_receipt
    with pytest.raises(ReceiptValidationError, match="receipt_invalid"):
        validate_acceptance_receipt(unsafe_receipt, json.dumps(expected))

    unsafe_nested_receipt = valid_receipt.replace(
        '"model": "codex-model-fixture"',
        '"model": "https://private.example/model", "model": "codex-model-fixture"',
        1,
    )
    assert unsafe_nested_receipt != valid_receipt
    with pytest.raises(ReceiptValidationError, match="receipt_invalid"):
        validate_acceptance_receipt(unsafe_nested_receipt, json.dumps(expected))

    unsafe_expected = json.dumps(expected).replace(
        '"model": "codex-model-fixture"',
        '"model": "https://private.example/model", "model": "codex-model-fixture"',
        1,
    )
    with pytest.raises(ReceiptValidationError, match="expected_route_invalid"):
        validate_acceptance_receipt(valid_receipt, unsafe_expected)

    receipt_path = tmp_path / "duplicate-receipt.json"
    expected_path = tmp_path / "expected-route.json"
    receipt_path.write_text(unsafe_receipt, encoding="utf-8")
    expected_path.write_text(json.dumps(expected), encoding="utf-8")

    assert main(["--input", str(receipt_path), "--expected-route", str(expected_path)]) == 2
    output = capsys.readouterr().out
    assert output == "receipt_invalid\n"
    assert "do-not-print-this-value" not in output

    receipt_path.write_text(valid_receipt, encoding="utf-8")
    expected_path.write_text(unsafe_expected, encoding="utf-8")
    assert main(["--input", str(receipt_path), "--expected-route", str(expected_path)]) == 2
    output = capsys.readouterr().out
    assert output == "expected_route_invalid\n"
    assert "private.example" not in output


def test_missing_host_prerequisite_is_reported_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt = {
        "receipt_type": "model_access_router.macos_executor_acceptance.v3",
        "status": "incomplete",
        "route": _expected_route()["route"],
        "catalog_snapshot_hash": None,
        "executor_profile": "product_codex_executor",
        "configured_path_profiles": ["ygg_vlan_primary"],
        "selected_path_profile": None,
        "path_selection_reason": "not_selected",
        "completion_dispatched": False,
        "missing_prerequisites": [
            "codex_cli_unavailable",
            "tailscale_path_unconfigured",
            "catalog_snapshot_unavailable",
        ],
    }
    receipt_path = tmp_path / "incomplete-receipt.json"
    expected_path = tmp_path / "expected-route.json"
    receipt_bytes = json.dumps(receipt).encode("utf-8")
    expected_bytes = json.dumps(_expected_route()).encode("utf-8")
    receipt_path.write_bytes(receipt_bytes)
    expected_path.write_bytes(expected_bytes)

    def forbidden_operation(*args: object, **kwargs: object) -> None:
        pytest.fail("offline receipt validation attempted an external operation")

    monkeypatch.setattr(subprocess, "run", forbidden_operation)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden_operation)
    monkeypatch.setattr(socket, "create_connection", forbidden_operation)

    assert main(["--input", str(receipt_path), "--expected-route", str(expected_path)]) == 1
    assert capsys.readouterr().out == (
        "incomplete missing=codex_cli_unavailable,tailscale_path_unconfigured,"
        "catalog_snapshot_unavailable\n"
    )
    assert receipt_path.read_bytes() == receipt_bytes
    assert expected_path.read_bytes() == expected_bytes
