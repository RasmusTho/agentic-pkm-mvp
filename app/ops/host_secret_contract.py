"""Value-free contract for host-local Keychain secret consumers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONTRACT_PATH = Path("config/secrets/host_secret_contract.json")
_CONTRACT_FIELDS = frozenset({"version", "keychain_service", "keychain_account_template", "consumers"})
_CONSUMER_FIELDS = frozenset({"channel", "consumer", "secrets"})
_KEYCHAIN_ACCOUNT_TEMPLATE = "{channel}:{consumer}:{secret}"


class UndeclaredSecretConsumerError(ValueError):
    """Raised without secret material when a consumer requests an undeclared key."""


@dataclass(frozen=True)
class HostSecretContract:
    keychain_service: str
    keychain_account_template: str
    allowed: frozenset[tuple[str, str, str]]

    def require_declared(self, *, channel: str, consumer: str, secret: str) -> None:
        if (channel, consumer, secret) not in self.allowed:
            raise UndeclaredSecretConsumerError(
                f"undeclared host secret request: channel={channel!r}, consumer={consumer!r}, secret={secret!r}"
            )

    def keychain_account(self, *, channel: str, consumer: str, secret: str) -> str:
        """Return the declared, channel-scoped Keychain account identifier."""
        self.require_declared(channel=channel, consumer=consumer, secret=secret)
        return self.keychain_account_template.format(
            channel=channel, consumer=consumer, secret=secret
        )


def load_host_secret_contract(path: Path = DEFAULT_CONTRACT_PATH) -> HostSecretContract:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != _CONTRACT_FIELDS:
        raise ValueError("invalid host secret contract")
    if (
        payload["version"] != 1
        or not isinstance(payload["keychain_service"], str)
        or payload["keychain_account_template"] != _KEYCHAIN_ACCOUNT_TEMPLATE
        or not isinstance(payload["consumers"], list)
    ):
        raise ValueError("invalid host secret contract")
    allowed: set[tuple[str, str, str]] = set()
    for item in payload["consumers"]:
        if not isinstance(item, dict) or set(item) != _CONSUMER_FIELDS:
            raise ValueError("invalid host secret consumer declaration")
        channel, consumer, secrets = item["channel"], item["consumer"], item["secrets"]
        if not isinstance(channel, str) or not isinstance(consumer, str) or not isinstance(secrets, list):
            raise ValueError("invalid host secret consumer declaration")
        for secret in secrets:
            if not isinstance(secret, str):
                raise ValueError("invalid host secret identifier")
            allowed.add((channel, consumer, secret))
    if not allowed:
        raise ValueError("host secret contract declares no consumers")
    return HostSecretContract(
        keychain_service=payload["keychain_service"],
        keychain_account_template=payload["keychain_account_template"],
        allowed=frozenset(allowed),
    )
