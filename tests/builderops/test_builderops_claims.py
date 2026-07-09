from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_root


def _env(tmp_path: Path) -> dict[str, str]:
    return {
        "BUILDEROPS_VAULT_ROOT": str(tmp_path / "shared"),
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }


def _run(args: list[str], env: dict[str, str]):
    return CliRunner().invoke(builderops_root, ["builderops", *args], env=env, catch_exceptions=False)


def _ticket(vault: Path) -> None:
    path = vault / "agent-delivery" / "Ready" / "BMI-01.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('---\nid: "BMI-01"\nstatus: "Ready"\n---\n\n# BMI-01\n', encoding="utf-8")


def test_shared_advisory_claims_allow_concurrent_agents_and_release_own_claims(tmp_path: Path) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    _ticket(vault)

    first = _run(["vault", "claim", str(vault), "BMI-01", "--agent", "codex", "--json"], env)
    second = _run(["vault", "claim", str(vault), "BMI-01", "--agent", "claude", "--json"], env)
    released = _run(["vault", "release", str(vault), "BMI-01", "--agent", "codex", "--json"], env)

    assert first.exit_code == 0
    assert json.loads(first.output)["claim_scope"] == "shared-advisory"
    assert second.exit_code == 0
    assert released.exit_code == 0
    assert not list((vault / ".builderops" / "claims").glob("BMI-01-codex-*.json"))
    assert list((vault / ".builderops" / "claims").glob("BMI-01-claude-*.json"))


def test_stale_advisory_claim_is_reported_without_exclusive_takeover(tmp_path: Path) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    _ticket(vault)
    claims = vault / ".builderops" / "claims"
    claims.mkdir(parents=True)
    (claims / "BMI-01-codex-old.json").write_text(json.dumps({"ticket_id": "BMI-01", "agent": "codex", "expires_at": "2020-01-01T00:00:00Z"}), encoding="utf-8")

    claimed = _run(["vault", "claim", str(vault), "BMI-01", "--agent", "claude", "--json"], env)
    validated = _run(["vault", "validate", str(vault), "--json"], env)

    assert claimed.exit_code == 0
    assert json.loads(claimed.output)["claim"]["agent"] == "claude"
    assert any(item["stale"] for item in json.loads(validated.output)["advisory_claims"]["claims"])


def test_claim_rejects_ready_yaml_outside_ready_folder(tmp_path: Path) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    path = vault / "agent-delivery" / "Backlog" / "BMI-01.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '---\nid: "BMI-01"\nstatus: "Ready"\n---\n\n# BMI-01\n',
        encoding="utf-8",
    )

    result = _run(
        ["vault", "claim", str(vault), "BMI-01", "--agent", "codex", "--json"],
        env,
    )

    assert result.exit_code != 0
    assert "is not Ready" in result.output
    assert not list((vault / ".builderops" / "claims").glob("*.json"))


def test_claim_rejects_unsafe_ticket_id_without_writing_outside_claims(tmp_path: Path) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    path = vault / "agent-delivery" / "Ready" / "unsafe.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '---\nid: "../escape"\nstatus: "Ready"\n---\n\n# unsafe\n',
        encoding="utf-8",
    )

    result = _run(
        ["vault", "claim", str(vault), "unsafe", "--agent", "codex", "--json"],
        env,
    )

    assert result.exit_code != 0
    assert "unsafe ticket id" in result.output
    assert not (vault / ".builderops" / "escape").exists()
