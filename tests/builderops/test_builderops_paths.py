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
    assert "forbidden SQLite state" in result.output


def test_rejects_configured_sqlite_under_shared_vault(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"

    with pytest.raises(ValueError, match="BUILDEROPS_DB_PATH"):
        load_paths(
            {
                "BUILDEROPS_VAULT_ROOT": str(vault),
                "BUILDEROPS_DB_PATH": str(vault / "builderops.sqlite3"),
            }
        )


def test_validate_rejects_mismatched_configured_root(tmp_path: Path) -> None:
    configured = tmp_path / "configured-vault"
    other = tmp_path / "other-vault"
    env = {
        "BUILDEROPS_VAULT_ROOT": str(configured),
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }

    result = _run(["vault", "validate", str(other), "--json"], env)

    assert result.exit_code != 0
    assert "does not match BUILDEROPS_VAULT_ROOT" in result.output


def test_global_db_path_override_is_used_by_paths_and_validation(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    env = {
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "BUILDEROPS_DB_PATH": str(tmp_path / "safe" / "builderops.sqlite3"),
    }
    override = vault / "override.sqlite3"

    paths = _run(
        ["--db-path", str(override), "vault", "paths", "--json"],
        env,
    )
    validated = _run(
        ["--db-path", str(override), "vault", "validate", str(vault), "--json"],
        env,
    )

    assert paths.exit_code != 0
    assert "BUILDEROPS_DB_PATH" in paths.output
    assert validated.exit_code != 0
    assert "BUILDEROPS_DB_PATH" in validated.output


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("state.db", "not a database"),
        ("opaque-state", b"SQLite format 3\x00" + b"\x00" * 16),
    ],
)
def test_validate_rejects_nested_sqlite_file(
    tmp_path: Path,
    filename: str,
    content: str | bytes,
) -> None:
    vault = tmp_path / "shared-vault"
    env = {
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }
    nested = vault / "transient" / filename
    nested.parent.mkdir(parents=True)
    if isinstance(content, bytes):
        nested.write_bytes(content)
    else:
        nested.write_text(content, encoding="utf-8")

    result = _run(["vault", "validate", str(vault), "--json"], env)

    assert result.exit_code != 0
    assert str(nested) in result.output
