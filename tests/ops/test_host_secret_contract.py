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
