from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_root
from app.builderops.config import load_paths


def _run(args: list[str], env: dict[str, str]):
    return CliRunner().invoke(builderops_root, ["builderops", *args], env=env, catch_exceptions=False)


def test_resolves_shared_vault_and_local_state_independently(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    paths = load_paths(
        {
            "BUILDEROPS_VAULT_ROOT": str(vault),
            "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
            "BUILDEROPS_CLAIMS_ROOT": str(tmp_path / "local" / "claims"),
        }
    )

    assert paths.vault_root == vault
    assert paths.db_path.parent != vault


def test_shared_vault_bootstrap_creates_advisory_claims_but_never_sqlite(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    env = {
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }

    result = _run(["vault", "init", str(vault), "--json"], env)

    assert result.exit_code == 0
    assert (vault / "agent-delivery" / "Ready").is_dir()
    assert not (vault / "builderops.sqlite3").exists()
    assert (vault / ".builderops" / "claims").is_dir()


def test_rejects_sqlite_but_allows_advisory_claim_state_inside_shared_vault(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    env = {
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }
    _run(["vault", "init", str(vault), "--json"], env)
    (vault / "builderops.sqlite3").write_text("not a database", encoding="utf-8")

    result = _run(["vault", "validate", str(vault), "--json"], env)

    assert result.exit_code != 0
    assert "forbidden local operational state" in result.output


def test_rejects_configured_sqlite_under_shared_vault(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"

    with pytest.raises(ValueError, match="BUILDEROPS_DB_PATH"):
        load_paths(
            {
                "BUILDEROPS_VAULT_ROOT": str(vault),
                "BUILDEROPS_DB_PATH": str(vault / "builderops.sqlite3"),
            }
        )
