#!/usr/bin/env python3
"""Report value-free production prerequisites for the devUI Focus GitHub read."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from app.ops.host_secret_bootstrap import _security_keychain_lookup
from app.ops.host_secret_contract import HostSecretContract, load_host_secret_contract
from app.release_channels.channel_isolation_preflight import _load_compose


_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXPECTED_REPOSITORY = "RasmusTho/agentic-pkm-mvp"
_CHANNEL = "prod"
_CONSUMER = "heimdal-api-ingress"
_CREDENTIALS = (
    ("github.token", "github_token_present"),
    ("heimdal.raw-store-key", "heimdal_raw_store_key_present"),
)


def _load_prod_repository_binding() -> object:
    compose = _load_compose(_REPO_ROOT / "docker-compose.prod.yml")
    return compose["services"]["api"]["environment"].get("COCKPIT_GITHUB_REPO")


def _lookup_present(contract: HostSecretContract, logical_id: str) -> bool:
    account = contract.keychain_account(
        channel=_CHANNEL,
        consumer=_CONSUMER,
        secret=logical_id,
    )
    value = _security_keychain_lookup(contract.keychain_service, account)
    try:
        return bool(value)
    finally:
        del value


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def main() -> int:
    payload: dict[str, Any] = {
        "repository": None,
        "github_token_present": False,
        "heimdal_raw_store_key_present": False,
    }

    try:
        repository = _load_prod_repository_binding()
    except Exception:
        print("repository: configuration unavailable", file=sys.stderr)
        _emit(payload)
        return 1

    payload["repository"] = repository if isinstance(repository, str) else None
    if repository != _EXPECTED_REPOSITORY:
        print("repository: unexpected binding", file=sys.stderr)
        _emit(payload)
        return 1

    try:
        contract = load_host_secret_contract(
            _REPO_ROOT / "config/secrets/host_secret_contract.json"
        )
    except Exception:
        for logical_id, _output_key in _CREDENTIALS:
            print(f"{logical_id}: declaration unavailable", file=sys.stderr)
        _emit(payload)
        return 1

    for logical_id, output_key in _CREDENTIALS:
        try:
            payload[output_key] = _lookup_present(contract, logical_id)
        except Exception:
            print(f"{logical_id}: unavailable", file=sys.stderr)
        else:
            if not payload[output_key]:
                print(f"{logical_id}: unavailable", file=sys.stderr)

    _emit(payload)
    return 0 if all(payload[key] is True for _logical_id, key in _CREDENTIALS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
