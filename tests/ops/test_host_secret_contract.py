import json
from pathlib import Path
import traceback
from unittest.mock import Mock

import pytest

from app.ops import host_secret_bootstrap
from app.ops.host_secret_contract import (
    HostSecretContract,
    UndeclaredSecretConsumerError,
    load_host_secret_contract,
)
from app.ops.host_secret_controller import HostSecretController


def test_contract_rejects_undeclared_consumer_secret_pair() -> None:
    contract = load_host_secret_contract()

    contract.require_declared(
        channel="dev", consumer="heimdal-capture-watch", secret="heimdal.raw-store-key"
    )

    with pytest.raises(UndeclaredSecretConsumerError, match="undeclared host secret request"):
        contract.require_declared(channel="dev", consumer="heimdal-capture-watch", secret="unrelated-key")


def test_undeclared_request_error_does_not_disclose_caller_identifiers() -> None:
    contract = load_host_secret_contract()
    raw_channel = "noncanonical-channel"
    raw_consumer = "noncanonical-consumer"
    raw_secret = "raw-key-material"

    with pytest.raises(UndeclaredSecretConsumerError) as error:
        contract.require_declared(channel=raw_channel, consumer=raw_consumer, secret=raw_secret)

    message = str(error.value)
    assert message == "undeclared host secret request"
    assert raw_channel not in message
    assert raw_consumer not in message
    assert raw_secret not in message


def test_contract_is_value_free() -> None:
    text = Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8")

    assert "value" not in text


def test_contract_resolves_distinct_channel_scoped_keychain_accounts() -> None:
    contract = load_host_secret_contract()

    accounts = {
        contract.keychain_account(
            channel=channel,
            consumer="heimdal-capture-watch",
            secret="heimdal.raw-store-key",
        )
        for channel in ("dev", "test", "prod")
    }

    assert accounts == {
        "dev:heimdal-capture-watch:heimdal.raw-store-key",
        "test:heimdal-capture-watch:heimdal.raw-store-key",
        "prod:heimdal-capture-watch:heimdal.raw-store-key",
    }


def test_contract_percent_encodes_components_to_prevent_account_collisions() -> None:
    contract = HostSecretContract(
        keychain_service="test",
        keychain_account_template="{channel}:{consumer}:{secret}",
        allowed=frozenset(
            {
                ("dev:ops", "watch", "key"),
                ("dev", "ops:watch", "key"),
            }
        ),
    )

    left = contract.keychain_account(channel="dev:ops", consumer="watch", secret="key")
    right = contract.keychain_account(channel="dev", consumer="ops:watch", secret="key")

    assert left == "dev%3Aops:watch:key"
    assert right == "dev:ops%3Awatch:key"
    assert left != right


def test_contract_rejects_undeclared_consumer_field(tmp_path: Path) -> None:
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8"))
    payload["consumers"][0]["raw_key"] = "not-a-secret-value"
    contract_path = tmp_path / "host_secret_contract.json"
    contract_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid host secret consumer declaration"):
        load_host_secret_contract(contract_path)


def test_contract_rejects_consumer_optional_secret_without_grant(tmp_path: Path) -> None:
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8"))
    payload["consumers"][0]["optional_secrets"] = ["discord.webhook"]
    contract_path = tmp_path / "host_secret_contract.json"
    contract_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid host secret consumer declaration"):
        load_host_secret_contract(contract_path)


def test_contract_rejects_undeclared_top_level_field(tmp_path: Path) -> None:
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8"))
    payload["raw_key"] = "not-a-secret-value"
    contract_path = tmp_path / "host_secret_contract.json"
    contract_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid host secret contract"):
        load_host_secret_contract(contract_path)


@pytest.mark.parametrize("surface", ["top", "secret", "consumer"])
def test_contract_rejects_value_bearing_field(
    tmp_path: Path,
    surface: str,
) -> None:
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8"))
    if surface == "top":
        payload["value"] = "actual-secret-material"
    elif surface == "secret":
        payload["secrets"][0]["value"] = "actual-secret-material"
    else:
        payload["consumers"][0]["value"] = "actual-secret-material"
    contract_path = tmp_path / "host_secret_contract.json"
    contract_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid host secret"):
        load_host_secret_contract(contract_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [("keychain_service", "actual-secret-material"), ("version", True)],
)
def test_contract_rejects_noncanonical_top_level_values(
    tmp_path: Path, field: str, value: str | bool
) -> None:
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8"))
    payload[field] = value
    contract_path = tmp_path / "host_secret_contract.json"
    contract_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid host secret contract"):
        load_host_secret_contract(contract_path)


def test_contract_rejects_duplicate_json_key_that_hides_secret_material(tmp_path: Path) -> None:
    text = Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8")
    text = text.replace(
        '"keychain_service": "yggdrasil.host-secrets",',
        '"keychain_service": "actual-secret-material",\n'
        '  "keychain_service": "yggdrasil.host-secrets",',
    )
    contract_path = tmp_path / "host_secret_contract.json"
    contract_path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate host secret contract key"):
        load_host_secret_contract(contract_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [("channels", ["dev", "secret-value"]), ("consumer", "secret-value")],
)
def test_contract_rejects_unknown_channel_or_consumer(
    tmp_path: Path, field: str, value: str | list[str]
) -> None:
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8"))
    if field == "channels":
        payload["channels"] = value
    else:
        payload["consumers"][0][field] = value
    contract_path = tmp_path / "host_secret_contract.json"
    contract_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid host secret"):
        load_host_secret_contract(contract_path)


def test_model_provider_identifiers_are_declared_data() -> None:
    source = Path("app/ops/host_secret_contract.py").read_text(encoding="utf-8")
    contract = load_host_secret_contract()

    assert "_INITIAL_CHANNELS" not in source
    assert "_INITIAL_CONSUMER" not in source
    assert "_INITIAL_SECRET" not in source
    assert contract.binding_for("openai.api-key") == "OPENAI_API_KEY"
    assert contract.binding_for("anthropic.api-key") == "ANTHROPIC_API_KEY"
    assert contract.kind_for("openai.api-key") == "api-key"
    assert contract.kind_for("anthropic.api-key") == "api-key"


def test_discord_external_alert_binding_is_value_free() -> None:
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8"))
    contract = load_host_secret_contract()

    assert contract.binding_for("discord.webhook") == "DISCORD_WEBHOOK"
    assert contract.kind_for("discord.webhook") == "webhook"
    assert contract.keychain_account(
        channel="prod",
        consumer="heimdal-external-alerts",
        secret="discord.webhook",
    ) == "prod:heimdal-external-alerts:discord.webhook"
    for channel in ("dev", "test", "prod"):
        contract.require_declared(
            channel=channel,
            consumer="heimdal-external-alerts",
            secret="discord.webhook",
        )

    assert "value" not in json.dumps(payload).lower()


def test_model_inquiry_secret_contract_is_exact_and_value_free() -> None:
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8"))
    contract = load_host_secret_contract()

    assert payload["channels"] == ["dev", "test", "prod"]
    assert payload["secrets"] == [
        {
            "logical_id": "heimdal.raw-store-key",
            "child_binding": "HEIMDAL_RAW_STORE_KEY",
            "kind": "raw-store-key",
            "optional": False,
            # #4512/#3848: fed by the capture, API ingress, and one-shot
            # migration consumers into one AES-256-GCM cipher domain.
            "shared_key_domain": True,
        },
        {
            "logical_id": "openai.api-key",
            "child_binding": "OPENAI_API_KEY",
            "kind": "api-key",
            "optional": False,
            "shared_key_domain": False,
        },
        {
            "logical_id": "anthropic.api-key",
            "child_binding": "ANTHROPIC_API_KEY",
            "kind": "api-key",
            "optional": False,
            "shared_key_domain": False,
        },
        # #4489: the cockpit's live GitHub read wants a token, but the api
        # consumer's layer must keep materializing for hosts that have none.
        {
            "logical_id": "github.token",
            "child_binding": "GITHUB_TOKEN",
            "kind": "token",
            "optional": True,
            "shared_key_domain": False,
        },
        {
            "logical_id": "heimdal.archive-pass",
            "child_binding": "HEIMDAL_ARCHIVE_PASS",
            "kind": "archive-pass",
            "optional": False,
            "shared_key_domain": False,
        },
        {
            "logical_id": "discord.webhook",
            "child_binding": "DISCORD_WEBHOOK",
            "kind": "webhook",
            "optional": False,
            "shared_key_domain": False,
        },
        {
            "logical_id": "typesafe.api-key",
            "child_binding": "TYPESAFE_API_KEY",
            "kind": "api-key",
            "optional": False,
            "shared_key_domain": False,
        },
    ]
    assert payload["consumers"] == [
        {
            "consumer": "heimdal-api-ingress",
            "channels": ["dev", "test", "prod"],
            "secrets": ["heimdal.raw-store-key", "github.token"],
            "optional_secrets": ["heimdal.raw-store-key"],
            "role_requirements": {},
        },
        {
            "consumer": "heimdal-raw-migrate",
            "channels": ["dev", "test", "prod"],
            "secrets": ["heimdal.raw-store-key"],
            "optional_secrets": [],
            "role_requirements": {},
        },
        {
            "consumer": "heimdal-capture-watch",
            "channels": ["dev", "test", "prod"],
            "secrets": ["heimdal.raw-store-key"],
            "optional_secrets": [],
            "role_requirements": {},
        },
        {
            "consumer": "heimdal-cold-volume",
            "channels": ["dev", "test", "prod"],
            "secrets": ["heimdal.archive-pass"],
            "optional_secrets": [],
            "role_requirements": {},
        },
        {
            "consumer": "builderops-model-inquiry",
            "channels": ["dev", "test", "prod"],
            "secrets": ["openai.api-key"],
            "optional_secrets": [],
            "role_requirements": {
                "model_inquiry": ["openai.api-key"],
            },
        },
        {
            "consumer": "builderops-ckm-semantic",
            "channels": ["dev", "test", "prod"],
            "secrets": ["openai.api-key"],
            "optional_secrets": [],
            "role_requirements": {
                "ckm_semantic": ["openai.api-key"],
            },
        },
        {
            "consumer": "heimdal-external-alerts",
            "channels": ["dev", "test", "prod"],
            "secrets": ["discord.webhook"],
            "optional_secrets": [],
            "role_requirements": {},
        },
        {
            "consumer": "marr-server-dev",
            "channels": ["dev"],
            "secrets": ["typesafe.api-key"],
            "optional_secrets": [],
            "role_requirements": {},
        },
    ]
    assert all("design" not in item["consumer"] for item in payload["consumers"])
    assert contract.required_secrets_for_role(
        consumer="builderops-model-inquiry", role="model_inquiry"
    ) == ("openai.api-key",)
    assert contract.required_secrets_for_role(
        consumer="builderops-ckm-semantic", role="ckm_semantic"
    ) == ("openai.api-key",)
    assert "value" not in json.dumps(payload).lower()


@pytest.mark.parametrize(
    ("surface", "value"),
    [
        ("channel", "x" * 20),
        ("consumer", "secret-material"),
        ("logical_id", ("x" * 20) + ".api-key"),
        ("child_binding", "X" * 32),
        ("kind", "x" * 20),
        ("role", "x" * 20),
    ],
)
def test_identifier_grammar_rejects_out_of_grammar_names(
    tmp_path: Path,
    surface: str,
    value: str,
) -> None:
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8"))
    if surface == "channel":
        payload["channels"][0] = value
    elif surface == "consumer":
        payload["consumers"][0]["consumer"] = value
    elif surface == "role":
        payload["consumers"][1]["role_requirements"][value] = ["openai.api-key"]
    else:
        payload["secrets"][0][surface] = value
    contract_path = tmp_path / "host_secret_contract.json"
    contract_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid host secret"):
        load_host_secret_contract(contract_path)


def test_channel_isolation_holds_for_model_provider_secrets() -> None:
    contract = load_host_secret_contract()

    accounts = {
        channel: contract.keychain_account(
            channel=channel,
            consumer="builderops-model-inquiry",
            secret="openai.api-key",
        )
        for channel in ("dev", "test", "prod")
    }

    assert accounts == {
        "dev": "dev:builderops-model-inquiry:openai.api-key",
        "test": "test:builderops-model-inquiry:openai.api-key",
        "prod": "prod:builderops-model-inquiry:openai.api-key",
    }
    with pytest.raises(UndeclaredSecretConsumerError):
        contract.require_declared(
            channel="production",
            consumer="builderops-model-inquiry",
            secret="openai.api-key",
        )


def test_runtime_raw_store_consumers_declare_raw_store_key() -> None:
    """Every producer/transformer is declared for the shared raw-key domain.

    #4422 owns API ingress, capture-watch remains the original producer, and
    #3848 adds the exact one-shot migration transformer. All declarations are
    loaded through the production loader for every governed channel.
    """
    contract = load_host_secret_contract()
    for channel in ("dev", "test", "prod"):
        for consumer in (
            "heimdal-api-ingress",
            "heimdal-raw-migrate",
            "heimdal-capture-watch",
        ):
            contract.require_declared(
                channel=channel,
                consumer=consumer,
                secret="heimdal.raw-store-key",
            )
    with pytest.raises(UndeclaredSecretConsumerError):
        contract.require_declared(channel="dev", consumer="heimdal-api-ingress", secret="openai.api-key")


def test_cold_volume_consumer_declares_required_channel_scoped_passphrase() -> None:
    contract = load_host_secret_contract()

    assert contract.binding_for("heimdal.archive-pass") == "HEIMDAL_ARCHIVE_PASS"
    assert contract.kind_for("heimdal.archive-pass") == "archive-pass"
    assert contract.is_optional("heimdal.archive-pass") is False
    assert contract.is_shared_key_domain("heimdal.archive-pass") is False
    for channel in ("dev", "test", "prod"):
        contract.require_declared(
            channel=channel,
            consumer="heimdal-cold-volume",
            secret="heimdal.archive-pass",
        )


def test_raw_store_key_declares_shared_key_domain() -> None:
    """The raw key backs one cipher domain fed by all three consumers.

    Every declared consumer of `heimdal.raw-store-key` must resolve to
    identical material, so it is marked shared-domain. The model-provider
    secrets keep resolving independently per consumer and are not marked.
    """
    contract = load_host_secret_contract()

    assert contract.is_shared_key_domain("heimdal.raw-store-key") is True
    assert contract.is_shared_key_domain("openai.api-key") is False
    assert contract.is_shared_key_domain("anthropic.api-key") is False
    assert contract.is_shared_key_domain("github.token") is False
    assert contract.consumers_declared_for(
        channel="dev", secret="heimdal.raw-store-key"
    ) == frozenset(
        {
            "heimdal-capture-watch",
            "heimdal-api-ingress",
            "heimdal-raw-migrate",
        }
    )
    with pytest.raises(UndeclaredSecretConsumerError):
        contract.is_shared_key_domain("unrelated-key")


@pytest.mark.parametrize(
    ("shared_key_domain_value", "expected"),
    [
        pytest.param(..., "invalid host secret declaration", id="omitted"),
        pytest.param(1, "invalid host secret identifier", id="truthy-int"),
        pytest.param(0, "invalid host secret identifier", id="falsy-int"),
        pytest.param("true", "invalid host secret identifier", id="string"),
        pytest.param(None, "invalid host secret identifier", id="null"),
    ],
)
def test_loader_rejects_a_declaration_without_an_explicit_boolean_shared_key_domain(
    tmp_path: Path, shared_key_domain_value: object, expected: str
) -> None:
    payload = json.loads(
        Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8")
    )
    if shared_key_domain_value is ...:
        del payload["secrets"][0]["shared_key_domain"]
    else:
        payload["secrets"][0]["shared_key_domain"] = shared_key_domain_value
    contract_path = tmp_path / "host_secret_contract.json"
    contract_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=expected):
        load_host_secret_contract(contract_path)


def test_existing_consumer_environment_grants_are_unchanged() -> None:
    contract = load_host_secret_contract()
    expected = {
        "heimdal-api-ingress": {"heimdal.raw-store-key", "github.token"},
        "heimdal-raw-migrate": {"heimdal.raw-store-key"},
        "heimdal-capture-watch": {"heimdal.raw-store-key"},
        "heimdal-cold-volume": {"heimdal.archive-pass"},
        "builderops-model-inquiry": {"openai.api-key"},
        "builderops-ckm-semantic": {"openai.api-key"},
        "heimdal-external-alerts": {"discord.webhook"},
    }
    bws_grants = frozenset(
        grant for grant in contract.allowed if grant[2] not in contract.keychain_only_secrets
    )
    assert bws_grants == frozenset(
        (channel, consumer, secret)
        for channel in ("dev", "test", "prod")
        for consumer, secrets in expected.items()
        for secret in secrets
    ) | {("dev", "marr-server-dev", "typesafe.api-key")}
    assert "POSTGRES_PASSWORD" not in contract.child_bindings
    assert "DATABASE_PASSWORD" not in contract.child_bindings


def test_postgres_password_contract_is_file_only_and_consumer_set_is_closed() -> None:
    contract = load_host_secret_contract()
    expected = {
        "postgres-db": "db",
        "postgres-migrate": "migrate",
        "postgres-api": "api",
        "postgres-worker": "worker",
        "postgres-watcher": "watcher",
        "postgres-capture-watch": "heimdal-capture-watch",
    }
    for channel in ("dev", "test", "prod"):
        for consumer, service in expected.items():
            assert contract.file_binding(
                channel=channel, consumer=consumer, secret="postgres.password"
            ) == (
                service,
                "POSTGRES_PASSWORD_FILE" if service == "db" else "DATABASE_PASSWORD_FILE",
            )
            with pytest.raises(UndeclaredSecretConsumerError):
                contract.require_declared(
                    channel=channel, consumer=consumer, secret="postgres.password"
                )
    with pytest.raises(UndeclaredSecretConsumerError):
        contract.binding_for("postgres.password")
    with pytest.raises(UndeclaredSecretConsumerError):
        contract.file_binding(channel="dev", consumer="postgres-other", secret="postgres.password")


@pytest.mark.parametrize(
    "corruption",
    ["duplicate", "unknown", "scope", "project", "consumer", "file-consumer", "password-env"],
)
def test_bws_identity_scope_is_closed_and_consumer_grants_are_preserved(
    tmp_path: Path, corruption: str
) -> None:
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text())
    if corruption == "duplicate":
        payload["bws"]["identities"].append(payload["bws"]["identities"][0])
    elif corruption == "unknown":
        payload["bws"]["identities"][0]["logical_id"] = "unknown.secret"
    elif corruption == "scope":
        payload["bws"]["identities"][0]["scope"] = "shared"
    elif corruption == "project":
        payload["bws"]["channel_projects"]["dev"] = "prod"
    elif corruption == "consumer":
        payload["consumers"][0]["secrets"].append("openai.api-key")
    elif corruption == "file-consumer":
        payload["file_secrets"][0]["consumers"].append(
            {
                "consumer": "postgres-other",
                "service": "other",
                "path_binding": "DATABASE_PASSWORD_FILE",
            }
        )
    else:
        payload["file_secrets"][0]["child_binding"] = "POSTGRES_PASSWORD"
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_host_secret_contract(path)


_TYPESAFE_CANARY = "fixture-typesafe-never-in-diagnostics"


def test_typesafe_key_uses_non_prod_project_and_marr_only_consumer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The active provider key uses non-prod storage with an MARR-only grant."""
    contract = load_host_secret_contract()
    monkeypatch.setattr(host_secret_bootstrap.sys, "platform", "darwin")

    class Reader:
        calls = []

        def lookup(self, project: str, identity: str) -> str:
            self.calls.append((project, identity))
            return _TYPESAFE_CANARY

    reader = Reader()
    assert host_secret_bootstrap.resolve_host_secret_values(
        channel="dev",
        consumer="marr-server-dev",
        provider="bws",
        bws_reader=reader,
        controller=HostSecretController(tmp_path / "controller"),
    ) == {"typesafe.api-key": _TYPESAFE_CANARY}
    assert contract.bws_identity(
        channel="dev", consumer="marr-server-dev", secret="typesafe.api-key"
    ) == ("non-prod", "dev/typesafe.api-key")
    assert reader.calls == [("non-prod", "dev/typesafe.api-key")]
    keychain_lookup = Mock(return_value=_TYPESAFE_CANARY)
    with pytest.raises(host_secret_bootstrap.HostSecretBootstrapError):
        host_secret_bootstrap.resolve_host_secret_values(
            channel="dev", consumer="marr-server-dev", provider="keychain",
            keychain_lookup=keychain_lookup,
        )
    keychain_lookup.assert_not_called()
    for consumer in ("product", "product-canvas", "builderops-ckm-semantic", "codex", "claude"):
        with pytest.raises(UndeclaredSecretConsumerError):
            contract.require_declared(channel="dev", consumer=consumer, secret="typesafe.api-key")
        with pytest.raises(UndeclaredSecretConsumerError):
            contract.bws_identity(channel="dev", consumer=consumer, secret="typesafe.api-key")
    assert contract.consumers_declared_for(channel="dev", secret="typesafe.api-key") == frozenset({"marr-server-dev"})
    assert contract.consumers_declared_for(channel="prod", secret="typesafe.api-key") == frozenset()


def test_bws_reader_project_assignments_are_not_channel_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    contract = load_host_secret_contract()
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text())
    assert contract.keychain_only_secrets == frozenset()
    assert {grant for grant in contract.allowed if grant[2] == "typesafe.api-key"} == {
        ("dev", "marr-server-dev", "typesafe.api-key")
    }
    assert payload["bws"]["channel_projects"] == {
        "dev": "non-prod", "test": "non-prod", "prod": "prod"
    }
    assert payload["bws"]["machine_accounts"] == {
        "admin": ["non-prod", "prod"],
        "non-prod-reader": ["non-prod", "prod"],
        "prod-reader": ["non-prod", "prod"],
    }
    assert payload["keychain_only_secrets"] == []
    assert {item["logical_id"]: item["scope"] for item in payload["bws"]["identities"]}[
        "typesafe.api-key"
    ] == "channel"
    assert contract.bws_identity(
        channel="dev", consumer="marr-server-dev", secret="typesafe.api-key"
    ) == ("non-prod", "dev/typesafe.api-key")


@pytest.mark.parametrize(
    ("platform", "channel", "consumer"),
    [
        ("darwin", "dev", "product-marr-dev"),
        ("darwin", "dev", "product-linux-runtime"),
        ("darwin", "dev", "builder-ckm-dev"),
        ("darwin", "dev", "builderops-ckm-semantic"),
        ("darwin", "dev", "builderops-model-inquiry"),
        ("darwin", "dev", "codex-agent-dev"),
        ("darwin", "dev", "claude-agent-dev"),
        ("darwin", "test", "marr-server-dev"),
        ("darwin", "prod", "marr-server-dev"),
        ("linux", "dev", "marr-server-dev"),
    ],
)
def test_typesafe_key_is_dev_only_and_agent_processes_cannot_resolve_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, channel: str, consumer: str
) -> None:
    monkeypatch.setattr(host_secret_bootstrap.sys, "platform", platform)
    calls: list[str] = []

    def lookup(_service: str, account: str) -> str:
        calls.append(account)
        assert not account.endswith(":typesafe.api-key")
        return "fixture-unrelated-provider-credential"

    if consumer in {"builderops-ckm-semantic", "builderops-model-inquiry"}:
        # Existing Builder grants remain usable; the MARR provider key never joins them.
        assert host_secret_bootstrap.resolve_host_secret_values(
            channel=channel, consumer=consumer, provider="keychain", keychain_lookup=lookup
        ) == {"openai.api-key": "fixture-unrelated-provider-credential"}
    elif (platform, channel, consumer) == ("darwin", "dev", "marr-server-dev"):
        reader = Mock()
        reader.lookup.return_value = _TYPESAFE_CANARY
        assert host_secret_bootstrap.resolve_host_secret_values(
            channel=channel,
            consumer=consumer,
            provider="bws",
            bws_reader=reader,
            controller=HostSecretController(tmp_path / "controller"),
        ) == {"typesafe.api-key": _TYPESAFE_CANARY}
        reader.lookup.assert_called_once_with("non-prod", "dev/typesafe.api-key")
        with pytest.raises(host_secret_bootstrap.HostSecretBootstrapError):
            host_secret_bootstrap.resolve_host_secret_values(
                channel=channel, consumer=consumer, provider="keychain", keychain_lookup=lookup
            )
        assert calls == []
    else:
        with pytest.raises(host_secret_bootstrap.HostSecretBootstrapError):
            host_secret_bootstrap.resolve_host_secret_values(
                channel=channel, consumer=consumer, provider="keychain", keychain_lookup=lookup
            )
        assert calls == []

        reader = Mock()
        with pytest.raises(host_secret_bootstrap.HostSecretBootstrapError):
            host_secret_bootstrap.resolve_host_secret_values(
                channel=channel, consumer=consumer, provider="bws", bws_reader=reader,
                controller=Mock(), keychain_lookup=lookup,
            )
        reader.lookup.assert_not_called()


@pytest.mark.parametrize(
    "fault",
    [
        "binding", "undeclared", "test-channel", "second-consumer", "optional",
        "shared-domain", "missing-bws-identity", "wrong-bws-scope", "keychain-only",
    ],
)
def test_typesafe_key_missing_or_unauthorized_binding_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture, fault: str,
) -> None:
    monkeypatch.setattr(host_secret_bootstrap.sys, "platform", "darwin")
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text())
    secret = next(item for item in payload["secrets"] if item["logical_id"] == "typesafe.api-key")
    consumer = next(item for item in payload["consumers"] if item["consumer"] == "marr-server-dev")
    if fault == "binding":
        secret["child_binding"] = _TYPESAFE_CANARY
    elif fault == "undeclared":
        payload["secrets"].remove(secret)
    elif fault == "test-channel":
        consumer["channels"].append("test")
    elif fault == "second-consumer":
        payload["consumers"].append({**consumer, "consumer": "codex-agent-dev"})
    elif fault == "optional":
        secret["optional"] = True
    elif fault == "shared-domain":
        secret["shared_key_domain"] = True
    elif fault == "missing-bws-identity":
        payload["bws"]["identities"] = [
            item for item in payload["bws"]["identities"] if item["logical_id"] != "typesafe.api-key"
        ]
    elif fault == "wrong-bws-scope":
        next(item for item in payload["bws"]["identities"] if item["logical_id"] == "typesafe.api-key")["scope"] = "shared"
    elif fault == "keychain-only":
        payload["keychain_only_secrets"] = ["typesafe.api-key"]
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(host_secret_bootstrap, "load_host_secret_contract", lambda: load_host_secret_contract(path))
    reader = Mock()
    controller = Mock()

    with pytest.raises(host_secret_bootstrap.HostSecretBootstrapError) as error:
        host_secret_bootstrap.resolve_host_secret_values(
            channel="dev", consumer="marr-server-dev", provider="bws", bws_reader=reader,
            controller=controller,
        )
    reader.lookup.assert_not_called()
    output = capsys.readouterr()
    diagnostics = output.out + output.err + caplog.text + "".join(traceback.format_exception(error.value))
    assert _TYPESAFE_CANARY not in diagnostics
    assert error.value.__suppress_context__
