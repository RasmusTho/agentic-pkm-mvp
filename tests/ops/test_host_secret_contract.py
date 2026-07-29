import json
from pathlib import Path

import pytest

from app.ops.host_secret_contract import (
    HostSecretContract,
    UndeclaredSecretConsumerError,
    load_host_secret_contract,
)


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


def test_contract_rejects_undeclared_top_level_field(tmp_path: Path) -> None:
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8"))
    payload["raw_key"] = "not-a-secret-value"
    contract_path = tmp_path / "host_secret_contract.json"
    contract_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid host secret contract"):
        load_host_secret_contract(contract_path)


def test_contract_rejects_value_bearing_identifier_field(tmp_path: Path) -> None:
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8"))
    payload["consumers"][0]["secrets"] = ["actual-secret-material"]
    contract_path = tmp_path / "host_secret_contract.json"
    contract_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid host secret identifier"):
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


def test_model_inquiry_secret_contract_is_exact_and_value_free() -> None:
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8"))
    contract = load_host_secret_contract()

    assert payload["channels"] == ["dev", "test", "prod"]
    assert payload["secrets"] == [
        {
            "logical_id": "heimdal.raw-store-key",
            "child_binding": "HEIMDAL_RAW_STORE_KEY",
            "kind": "raw-store-key",
        },
        {
            "logical_id": "openai.api-key",
            "child_binding": "OPENAI_API_KEY",
            "kind": "api-key",
        },
        {
            "logical_id": "anthropic.api-key",
            "child_binding": "ANTHROPIC_API_KEY",
            "kind": "api-key",
        },
    ]
    assert payload["consumers"] == [
        {
            "consumer": "heimdal-capture-watch",
            "channels": ["dev", "test", "prod"],
            "secrets": ["heimdal.raw-store-key"],
            "role_requirements": {},
        },
        {
            "consumer": "builderops-model-inquiry",
            "channels": ["dev", "test", "prod"],
            "secrets": ["openai.api-key", "anthropic.api-key"],
            "role_requirements": {
                "gpt_codex": ["openai.api-key"],
                "fable": ["anthropic.api-key"],
            },
        },
    ]
    assert all(
        "ckm" not in item["consumer"] and "design" not in item["consumer"]
        for item in payload["consumers"]
    )
    assert contract.required_secrets_for_role(
        consumer="builderops-model-inquiry", role="gpt_codex"
    ) == ("openai.api-key",)
    assert contract.required_secrets_for_role(
        consumer="builderops-model-inquiry", role="fable"
    ) == ("anthropic.api-key",)
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
