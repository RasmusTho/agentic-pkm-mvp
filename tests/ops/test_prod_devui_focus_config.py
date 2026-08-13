from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ops.host_secret_contract import load_host_secret_contract
from app.release_channels.channel_isolation_preflight import _load_compose
from scripts import check_prod_devui_focus_prerequisites as preflight


_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO = "RasmusTho/agentic-pkm-mvp"
_CONSUMER = "heimdal-api-ingress"
_SECRETS = ("github.token", "heimdal.raw-store-key")


def _json_output(capsys: pytest.CaptureFixture[str]) -> tuple[dict[str, object], str]:
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert len(lines) == 1
    return json.loads(lines[0]), captured.err


def test_prod_binds_canonical_cockpit_github_repository_without_secret() -> None:
    prod = _load_compose(_REPO_ROOT / "docker-compose.prod.yml")
    environment = prod["services"]["api"]["environment"]
    assert environment["COCKPIT_GITHUB_REPO"] == _REPO
    assert "GITHUB_TOKEN" not in environment


def test_focus_credential_preflight_reports_coupled_presence_booleans_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, str]] = []

    def lookup(service: str, account: str) -> str:
        calls.append((service, account))
        return "present-but-never-rendered"

    monkeypatch.setattr(preflight, "_security_keychain_lookup", lookup)
    assert preflight.main() == 0
    payload, diagnostics = _json_output(capsys)

    assert payload == {
        "repository": _REPO,
        "github_token_present": True,
        "heimdal_raw_store_key_present": True,
    }
    assert diagnostics == ""
    contract = load_host_secret_contract()
    assert calls == [
        (
            contract.keychain_service,
            contract.keychain_account(channel="prod", consumer=_CONSUMER, secret=secret),
        )
        for secret in _SECRETS
    ]


@pytest.mark.parametrize("failure", ["absent", "unreadable", "undeclared", "wrong-repo"])
def test_focus_credential_preflight_failures_are_value_account_and_path_free(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    forbidden = (
        "credential-value-sentinel",
        "prod:heimdal-api-ingress:secret-account-sentinel",
        "/Users/operator/private/keychain-sentinel",
        "config/secrets/private-sentinel.json",
    )

    if failure == "wrong-repo":
        monkeypatch.setattr(
            preflight,
            "_load_prod_repository_binding",
            lambda: "somebody/incorrect-repository",
        )
    elif failure == "undeclared":
        real_contract = load_host_secret_contract()

        class UndeclaredContract:
            keychain_service = real_contract.keychain_service

            def keychain_account(self, **_kwargs: str) -> str:
                raise ValueError(" ".join(forbidden))

        monkeypatch.setattr(
            preflight,
            "load_host_secret_contract",
            lambda _path: UndeclaredContract(),
        )
    elif failure == "unreadable":
        monkeypatch.setattr(
            preflight,
            "_security_keychain_lookup",
            lambda _service, _account: (_ for _ in ()).throw(RuntimeError(" ".join(forbidden))),
        )
    else:
        monkeypatch.setattr(preflight, "_security_keychain_lookup", lambda _service, _account: "")

    assert preflight.main() != 0
    payload, diagnostics = _json_output(capsys)
    assert set(payload) == {
        "repository",
        "github_token_present",
        "heimdal_raw_store_key_present",
    }
    assert payload["github_token_present"] is False or payload["heimdal_raw_store_key_present"] is False
    rendered = json.dumps(payload) + diagnostics
    assert all(item not in rendered for item in forbidden)
    assert "Keychain" not in rendered


def test_prod_focus_repo_binding_is_owner_documented_without_delivery_claim() -> None:
    docs = (
        _REPO_ROOT / "docs/BUILDEROPS_COCKPIT/GITHUB_LIVE_PLANE.md",
        _REPO_ROOT / "docs/LOCAL_SECRET_PROVISIONING/README.md",
        _REPO_ROOT / "docs/OPERATIONS.md",
    )
    marker = "committed repository binding is not deployment or credential-presence evidence"
    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert _REPO in text
        assert "heimdal.raw-store-key" in text
        assert marker in text.lower(), path
