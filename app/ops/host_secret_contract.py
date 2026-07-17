"""Value-free contract for host-local Keychain secret consumers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


DEFAULT_CONTRACT_PATH = Path("config/secrets/host_secret_contract.json")
_CONTRACT_FIELDS = frozenset({"version", "keychain_service", "keychain_account_template", "consumers"})
_CONSUMER_FIELDS = frozenset({"channel", "consumer", "secrets"})
_KEYCHAIN_ACCOUNT_TEMPLATE = "{channel}:{consumer}:{secret}"
_KEYCHAIN_SERVICE = "yggdrasil.host-secrets"
_INITIAL_CHANNELS = frozenset({"dev", "test", "prod"})
_INITIAL_CONSUMER = "heimdal-capture-watch"
_INITIAL_SECRET = "heimdal.raw-store-key"


class UndeclaredSecretConsumerError(ValueError):
    """Raised without secret material when a consumer requests an undeclared key."""


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("duplicate host secret contract key")
        payload[key] = value
    return payload


@dataclass(frozen=True)
class HostSecretContract:
    keychain_service: str
    keychain_account_template: str
    allowed: frozenset[tuple[str, str, str]]

    def require_declared(self, *, channel: str, consumer: str, secret: str) -> None:
        if (channel, consumer, secret) not in self.allowed:
            raise UndeclaredSecretConsumerError("undeclared host secret request")

    def keychain_account(self, *, channel: str, consumer: str, secret: str) -> str:
        """Return the declared, channel-scoped Keychain account identifier."""
        self.require_declared(channel=channel, consumer=consumer, secret=secret)
        return self.keychain_account_template.format(
            channel=quote(channel, safe=""),
            consumer=quote(consumer, safe=""),
            secret=quote(secret, safe=""),
        )


def load_host_secret_contract(path: Path = DEFAULT_CONTRACT_PATH) -> HostSecretContract:
    payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_json_keys)
    if not isinstance(payload, dict) or set(payload) != _CONTRACT_FIELDS:
        raise ValueError("invalid host secret contract")
    if (
        type(payload["version"]) is not int
        or payload["version"] != 1
        or payload["keychain_service"] != _KEYCHAIN_SERVICE
        or payload["keychain_account_template"] != _KEYCHAIN_ACCOUNT_TEMPLATE
        or not isinstance(payload["consumers"], list)
    ):
        raise ValueError("invalid host secret contract")
    allowed: set[tuple[str, str, str]] = set()
    for item in payload["consumers"]:
        if not isinstance(item, dict) or set(item) != _CONSUMER_FIELDS:
            raise ValueError("invalid host secret consumer declaration")
        channel, consumer, secrets = item["channel"], item["consumer"], item["secrets"]
        if (
            not isinstance(channel, str)
            or channel not in _INITIAL_CHANNELS
            or not isinstance(consumer, str)
            or consumer != _INITIAL_CONSUMER
            or not isinstance(secrets, list)
        ):
            raise ValueError("invalid host secret consumer declaration")
        for secret in secrets:
            if secret != _INITIAL_SECRET:
                raise ValueError("invalid host secret identifier")
            allowed.add((channel, consumer, secret))
    if not allowed:
        raise ValueError("host secret contract declares no consumers")
    return HostSecretContract(
        keychain_service=payload["keychain_service"],
        keychain_account_template=payload["keychain_account_template"],
        allowed=frozenset(allowed),
    )
