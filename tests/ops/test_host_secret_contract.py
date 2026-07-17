import json
from pathlib import Path

import pytest

from app.ops.host_secret_contract import UndeclaredSecretConsumerError, load_host_secret_contract


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
