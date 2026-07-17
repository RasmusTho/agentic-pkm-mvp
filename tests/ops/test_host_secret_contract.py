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


def test_contract_is_value_free() -> None:
    text = Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8")

    assert "HEIMDAL_RAW_STORE_KEY" not in text
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
    [("channel", "secret-value"), ("consumer", "secret-value")],
)
def test_contract_rejects_unknown_channel_or_consumer(
    tmp_path: Path, field: str, value: str
) -> None:
    payload = json.loads(Path("config/secrets/host_secret_contract.json").read_text(encoding="utf-8"))
    payload["consumers"][0][field] = value
    contract_path = tmp_path / "host_secret_contract.json"
    contract_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid host secret consumer declaration"):
        load_host_secret_contract(contract_path)
