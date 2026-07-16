"""Value-free contract for host-local Keychain secret consumers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONTRACT_PATH = Path("config/secrets/host_secret_contract.json")


class UndeclaredSecretConsumerError(ValueError):
    """Raised without secret material when a consumer requests an undeclared key."""


@dataclass(frozen=True)
class HostSecretContract:
    keychain_service: str
    allowed: frozenset[tuple[str, str, str]]

    def require_declared(self, *, channel: str, consumer: str, secret: str) -> None:
        if (channel, consumer, secret) not in self.allowed:
            raise UndeclaredSecretConsumerError(
                f"undeclared host secret request: channel={channel!r}, consumer={consumer!r}, secret={secret!r}"
            )


def load_host_secret_contract(path: Path = DEFAULT_CONTRACT_PATH) -> HostSecretContract:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("keychain_service"), str):
        raise ValueError("invalid host secret contract")
    allowed: set[tuple[str, str, str]] = set()
    for item in payload.get("consumers", []):
        channel, consumer, secrets = item.get("channel"), item.get("consumer"), item.get("secrets")
        if not isinstance(channel, str) or not isinstance(consumer, str) or not isinstance(secrets, list):
            raise ValueError("invalid host secret consumer declaration")
        for secret in secrets:
            if not isinstance(secret, str):
                raise ValueError("invalid host secret identifier")
            allowed.add((channel, consumer, secret))
    if not allowed:
        raise ValueError("host secret contract declares no consumers")
    return HostSecretContract(keychain_service=payload["keychain_service"], allowed=frozenset(allowed))
