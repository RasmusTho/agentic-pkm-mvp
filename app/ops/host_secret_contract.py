"""Value-free contract for host-local Keychain secret consumers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import quote


DEFAULT_CONTRACT_PATH = Path("config/secrets/host_secret_contract.json")
_CONTRACT_FIELDS = frozenset(
    {
        "version",
        "keychain_service",
        "keychain_account_template",
        "channels",
        "secrets",
        "consumers",
    }
)
# `optional` is required on every declaration rather than defaulted (#4489):
# the schema is closed at every level, and a secret whose absence is tolerated
# is exactly the kind of thing that must be stated, not inferred from silence.
# `shared_key_domain` follows the same rule (#4512): whether every declared
# consumer of a secret must resolve to identical material is a property of
# the secret, and it must be stated explicitly rather than inferred from how
# many consumers happen to declare it.
_SECRET_FIELDS = frozenset(
    {"logical_id", "child_binding", "kind", "optional", "shared_key_domain"}
)
_CONSUMER_FIELDS = frozenset({"consumer", "channels", "secrets", "role_requirements"})
_KEYCHAIN_ACCOUNT_TEMPLATE = "{channel}:{consumer}:{secret}"
_KEYCHAIN_SERVICE = "yggdrasil.host-secrets"
_CHANNEL_PATTERN = re.compile(r"^[a-z][a-z0-9]{0,15}$")
_CONSUMER_PATTERN = re.compile(
    r"^[a-z][a-z0-9]{0,15}(?:-[a-z][a-z0-9]{0,15}){2,3}$"
)
_LOGICAL_SECRET_PATTERN = re.compile(
    r"^[a-z][a-z0-9]{0,15}\.[a-z][a-z0-9-]{0,15}$"
)
_CHILD_BINDING_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,15}$")
_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,15}$")
_IDENTIFIER_MAX_LENGTH = 128


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
    secret_definitions: tuple[tuple[str, str, str], ...] = ()
    role_requirements: tuple[tuple[str, str, tuple[str, ...]], ...] = ()
    # Kept beside `secret_definitions` rather than widening it: several callers
    # unpack that tuple positionally, and optionality is a property of the
    # declaration, not of the identifier/binding/kind triple.
    optional_secrets: frozenset[str] = frozenset()
    # Secrets every declared consumer must resolve to identical material for
    # (#4512). Kept beside `secret_definitions` for the same reason as
    # `optional_secrets`.
    shared_key_domain_secrets: frozenset[str] = frozenset()

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

    def binding_for(self, secret: str) -> str:
        for logical_id, child_binding, _kind in self.secret_definitions:
            if logical_id == secret:
                return child_binding
        raise UndeclaredSecretConsumerError("undeclared host secret request")

    def kind_for(self, secret: str) -> str:
        for logical_id, _child_binding, kind in self.secret_definitions:
            if logical_id == secret:
                return kind
        raise UndeclaredSecretConsumerError("undeclared host secret request")

    def is_optional(self, secret: str) -> bool:
        """Whether an *absent* declaration may be skipped rather than fail closed.

        Optionality covers absence only. A declared secret that resolves to a
        malformed value fails closed whether or not it is optional — see
        ``host_secret_bootstrap._resolve_consumer_environment``.
        """
        for logical_id, _child_binding, _kind in self.secret_definitions:
            if logical_id == secret:
                return secret in self.optional_secrets
        raise UndeclaredSecretConsumerError("undeclared host secret request")

    def is_shared_key_domain(self, secret: str) -> bool:
        """Whether every declared consumer of *secret* must hold identical material.

        A shared-domain secret backs one cipher domain fed by more than one
        consumer process; a value resolved by one consumer must match every
        other declared consumer's value for the same channel, or the domain
        has silently split. Non-shared-domain secrets (a per-consumer API key)
        are declared independently per consumer with no such requirement.
        """
        for logical_id, _child_binding, _kind in self.secret_definitions:
            if logical_id == secret:
                return secret in self.shared_key_domain_secrets
        raise UndeclaredSecretConsumerError("undeclared host secret request")

    def consumers_declared_for(self, *, channel: str, secret: str) -> frozenset[str]:
        """Every consumer declared for *secret* on *channel*."""
        return frozenset(
            declared_consumer
            for declared_channel, declared_consumer, declared_secret in self.allowed
            if declared_channel == channel and declared_secret == secret
        )

    def required_secrets_for_role(self, *, consumer: str, role: str) -> tuple[str, ...]:
        for declared_consumer, declared_role, secrets in self.role_requirements:
            if declared_consumer == consumer and declared_role == role:
                return secrets
        raise UndeclaredSecretConsumerError("undeclared host secret request")

    @property
    def child_bindings(self) -> tuple[str, ...]:
        return tuple(binding for _logical_id, binding, _kind in self.secret_definitions)


def _is_identifier(value: object, pattern: re.Pattern[str]) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= _IDENTIFIER_MAX_LENGTH
        and pattern.fullmatch(value) is not None
    )


def _validated_unique_string_list(
    value: object,
    *,
    pattern: re.Pattern[str],
    error: str,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(error)
    if any(not _is_identifier(item, pattern) for item in value):
        raise ValueError(error)
    if len(set(value)) != len(value):
        raise ValueError(error)
    return tuple(value)


def _expected_child_binding(logical_id: str) -> str:
    return logical_id.replace(".", "_").replace("-", "_").upper()


def load_host_secret_contract(path: Path = DEFAULT_CONTRACT_PATH) -> HostSecretContract:
    payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_json_keys)
    if not isinstance(payload, dict) or set(payload) != _CONTRACT_FIELDS:
        raise ValueError("invalid host secret contract")
    if (
        type(payload["version"]) is not int
        or payload["version"] != 1
        or payload["keychain_service"] != _KEYCHAIN_SERVICE
        or payload["keychain_account_template"] != _KEYCHAIN_ACCOUNT_TEMPLATE
        or not isinstance(payload["channels"], list)
        or not isinstance(payload["secrets"], list)
        or not isinstance(payload["consumers"], list)
    ):
        raise ValueError("invalid host secret contract")

    channels = _validated_unique_string_list(
        payload["channels"],
        pattern=_CHANNEL_PATTERN,
        error="invalid host secret channel declaration",
    )
    secret_definitions: list[tuple[str, str, str]] = []
    optional_secrets: set[str] = set()
    shared_key_domain_secrets: set[str] = set()
    for item in payload["secrets"]:
        if not isinstance(item, dict) or set(item) != _SECRET_FIELDS:
            raise ValueError("invalid host secret declaration")
        logical_id = item["logical_id"]
        child_binding = item["child_binding"]
        kind = item["kind"]
        optional = item["optional"]
        shared_key_domain = item["shared_key_domain"]
        if (
            not _is_identifier(logical_id, _LOGICAL_SECRET_PATTERN)
            or not _is_identifier(child_binding, _CHILD_BINDING_PATTERN)
            or not _is_identifier(kind, _KIND_PATTERN)
            or logical_id.rsplit(".", maxsplit=1)[1] != kind
            or child_binding != _expected_child_binding(logical_id)
            # `type(...) is not bool` rather than isinstance: bool is a subclass
            # of int, and a truthy 1 must not smuggle in an optional or
            # shared-domain secret.
            or type(optional) is not bool
            or type(shared_key_domain) is not bool
        ):
            raise ValueError("invalid host secret identifier")
        secret_definitions.append((logical_id, child_binding, kind))
        if optional:
            optional_secrets.add(logical_id)
        if shared_key_domain:
            shared_key_domain_secrets.add(logical_id)
    logical_ids = [item[0] for item in secret_definitions]
    child_bindings = [item[1] for item in secret_definitions]
    if (
        not secret_definitions
        or len(set(logical_ids)) != len(logical_ids)
        or len(set(child_bindings)) != len(child_bindings)
    ):
        raise ValueError("invalid host secret declaration")

    declared_channels = frozenset(channels)
    declared_secrets = frozenset(logical_ids)
    allowed: set[tuple[str, str, str]] = set()
    role_requirements: list[tuple[str, str, tuple[str, ...]]] = []
    declared_consumers: set[str] = set()
    for item in payload["consumers"]:
        if not isinstance(item, dict) or set(item) != _CONSUMER_FIELDS:
            raise ValueError("invalid host secret consumer declaration")
        consumer = item["consumer"]
        if (
            not _is_identifier(consumer, _CONSUMER_PATTERN)
            or consumer in declared_consumers
            or not isinstance(item["role_requirements"], dict)
        ):
            raise ValueError("invalid host secret consumer declaration")
        declared_consumers.add(consumer)
        consumer_channels = _validated_unique_string_list(
            item["channels"],
            pattern=_CHANNEL_PATTERN,
            error="invalid host secret consumer declaration",
        )
        secrets = _validated_unique_string_list(
            item["secrets"],
            pattern=_LOGICAL_SECRET_PATTERN,
            error="invalid host secret identifier",
        )
        if not set(consumer_channels).issubset(declared_channels) or not set(secrets).issubset(
            declared_secrets
        ):
            raise ValueError("invalid host secret consumer declaration")
        for channel in consumer_channels:
            for secret in secrets:
                allowed.add((channel, consumer, secret))
        for role, required in item["role_requirements"].items():
            if not _is_identifier(role, _ROLE_PATTERN):
                raise ValueError("invalid host secret consumer declaration")
            required_secrets = _validated_unique_string_list(
                required,
                pattern=_LOGICAL_SECRET_PATTERN,
                error="invalid host secret consumer declaration",
            )
            if not set(required_secrets).issubset(secrets):
                raise ValueError("invalid host secret consumer declaration")
            role_requirements.append((consumer, role, required_secrets))
    if not allowed:
        raise ValueError("host secret contract declares no consumers")
    return HostSecretContract(
        keychain_service=payload["keychain_service"],
        keychain_account_template=payload["keychain_account_template"],
        allowed=frozenset(allowed),
        secret_definitions=tuple(secret_definitions),
        role_requirements=tuple(role_requirements),
        optional_secrets=frozenset(optional_secrets),
        shared_key_domain_secrets=frozenset(shared_key_domain_secrets),
    )
