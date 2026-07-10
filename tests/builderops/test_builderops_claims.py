from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_root
from app.dispatcher.models import TaskRecord
from app.dispatcher.signboard import _render_task


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
    assert not list((vault / ".builderops" / "claims").glob("*.tmp"))


def test_stale_advisory_claim_is_reported_without_exclusive_takeover(tmp_path: Path) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    _ticket(vault)
    claims = vault / ".builderops" / "claims"
    claims.mkdir(parents=True)
    (claims / "BMI-01-codex-old.json").write_text(
        json.dumps(
            {
                "ticket_id": "BMI-01",
                "agent": "codex",
                "claimed_at": "2019-01-01T00:00:00Z",
                "expires_at": "2020-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

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


def test_claim_rejects_symlinked_claims_root(tmp_path: Path) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    _ticket(vault)
    outside = tmp_path / "outside"
    outside.mkdir()
    claims = vault / ".builderops" / "claims"
    claims.parent.mkdir(parents=True)
    try:
        claims.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    result = _run(
        ["vault", "claim", str(vault), "BMI-01", "--agent", "codex", "--json"],
        env,
    )

    assert result.exit_code != 0
    assert "must not be a symlink" in result.output
    assert not list(outside.glob("*.json"))


def test_claim_rejects_symlinked_builderops_parent_before_creating_claims(tmp_path: Path) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    _ticket(vault)
    outside = tmp_path / "outside"
    outside.mkdir()
    builderops = vault / ".builderops"
    try:
        builderops.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    result = _run(
        ["vault", "claim", str(vault), "BMI-01", "--agent", "codex", "--json"],
        env,
    )

    assert result.exit_code != 0
    assert "must not be a symlink" in result.output
    assert not (outside / "claims").exists()


def test_claim_rejects_symlinked_ready_directory(tmp_path: Path) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    outside = tmp_path / "outside-ready"
    outside.mkdir()
    (outside / "BMI-01.md").write_text(
        '---\nid: "BMI-01"\nstatus: "Ready"\n---\n\n# BMI-01\n',
        encoding="utf-8",
    )
    delivery = vault / "agent-delivery"
    delivery.mkdir(parents=True)
    try:
        (delivery / "Ready").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    validated = _run(["vault", "validate", str(vault), "--json"], env)
    claimed = _run(
        ["vault", "claim", str(vault), "BMI-01", "--agent", "codex", "--json"],
        env,
    )

    assert validated.exit_code != 0
    assert "must not be a symlink" in validated.output
    assert claimed.exit_code != 0
    assert "must not be a symlink" in claimed.output
    assert not list((vault / ".builderops" / "claims").glob("*.json"))


def test_validate_reports_malformed_advisory_claim_without_crashing(tmp_path: Path) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    _ticket(vault)
    claims = vault / ".builderops" / "claims"
    claims.mkdir(parents=True)
    malformed = claims / "BMI-01-partial.json"
    malformed.write_text('{"ticket_id":', encoding="utf-8")

    result = _run(["vault", "validate", str(vault), "--json"], env)

    assert result.exit_code != 0
    payload = json.loads(result.output.splitlines()[0])
    assert payload["ok"] is False
    assert any(str(malformed) in error for error in payload["errors"])


@pytest.mark.parametrize(
    "content",
    [
        '{"expires_at":"2030-01-01T00:00:00Z"}',
        b"\xff\xfe\x00",
    ],
)
def test_validate_rejects_incomplete_or_non_utf8_claims(
    tmp_path: Path,
    content: str | bytes,
) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    _ticket(vault)
    claims = vault / ".builderops" / "claims"
    claims.mkdir(parents=True)
    invalid = claims / "BMI-01-invalid.json"
    if isinstance(content, bytes):
        invalid.write_bytes(content)
    else:
        invalid.write_text(content, encoding="utf-8")

    result = _run(["vault", "validate", str(vault), "--json"], env)

    assert result.exit_code != 0
    payload = json.loads(result.output.splitlines()[0])
    assert payload["ok"] is False
    assert any(str(invalid) in error for error in payload["errors"])


def test_queue_rejects_symlinked_ticket_and_claim_leaves_without_external_access(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    ready = vault / "agent-delivery" / "Ready"
    claims = vault / ".builderops" / "claims"
    ready.mkdir(parents=True)
    claims.mkdir(parents=True)
    outside_ticket = tmp_path / "outside-ticket.md"
    outside_ticket.write_text(
        '---\nid: "BMI-01"\nstatus: "Ready"\n---\n\n# outside\n',
        encoding="utf-8",
    )
    outside_claim = tmp_path / "outside-claim.json"
    outside_claim.write_text(
        json.dumps(
            {
                "ticket_id": "BMI-01",
                "agent": "codex",
                "claimed_at": "2026-07-10T08:00:00Z",
                "expires_at": "2026-07-10T09:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    try:
        (ready / "BMI-01.md").symlink_to(outside_ticket)
        (claims / "BMI-01-codex-external.json").symlink_to(outside_claim)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    validated = _run(["vault", "validate", str(vault), "--json"], env)
    claimed = _run(
        ["vault", "claim", str(vault), "BMI-01", "--agent", "codex", "--json"],
        env,
    )
    released = _run(
        ["vault", "release", str(vault), "BMI-01", "--agent", "codex", "--json"],
        env,
    )

    assert validated.exit_code != 0
    assert "symlink" in validated.output.lower()
    assert claimed.exit_code != 0
    assert released.exit_code != 0
    assert outside_ticket.exists()
    assert outside_claim.exists()


def test_queue_rejects_symlinked_agent_delivery_ancestor_for_claim_and_release(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    aliased_delivery = vault / "aliased-delivery"
    _ticket(vault / "alias-source")
    source_delivery = vault / "alias-source" / "agent-delivery"
    aliased_delivery.parent.mkdir(parents=True, exist_ok=True)
    source_delivery.rename(aliased_delivery)
    try:
        (vault / "agent-delivery").symlink_to(aliased_delivery, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    claimed = _run(
        ["vault", "claim", str(vault), "BMI-01", "--agent", "codex", "--json"],
        env,
    )
    released = _run(
        ["vault", "release", str(vault), "BMI-01", "--agent", "codex", "--json"],
        env,
    )

    assert claimed.exit_code != 0
    assert "agent-delivery root must not be a symlink" in claimed.output
    assert released.exit_code != 0
    assert "agent-delivery root must not be a symlink" in released.output
    assert not (vault / ".builderops").exists()


@pytest.mark.parametrize(
    "frontmatter",
    [
        'status: "Ready"',
        'id: "BMI-01"',
        'id: "BMI-01"\nid: "BMI-02"\nstatus: "Ready"',
        '- id\n- status',
        '? [a, b]\n: x\nid: "BMI-01"\nstatus: "Ready"',
        'id: 123\nstatus: "Ready"',
        'id: "BMI-01"\nstatus: ["Ready"]',
        'id: "BMI-01"\nstatus: "ready"\ncolumn: 5',
        'id: "BMI-01"\nstatus: "unknown"',
    ],
)
def test_queue_rejects_incomplete_or_ambiguous_ticket_frontmatter(
    tmp_path: Path,
    frontmatter: str,
) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    ticket = vault / "agent-delivery" / "Ready" / "BMI-01.md"
    ticket.parent.mkdir(parents=True)
    ticket.write_text(f"---\n{frontmatter}\n---\n\n# ticket\n", encoding="utf-8")

    validated = _run(["vault", "validate", str(vault), "--json"], env)
    claimed = _run(
        ["vault", "claim", str(vault), "BMI-01", "--agent", "codex", "--json"],
        env,
    )

    assert validated.exit_code != 0
    assert claimed.exit_code != 0
    assert not list((vault / ".builderops" / "claims").glob("*.json"))


def test_queue_rejects_non_utf8_ticket_without_crashing(tmp_path: Path) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    ticket = vault / "agent-delivery" / "Ready" / "BMI-01.md"
    ticket.parent.mkdir(parents=True)
    ticket.write_bytes(b"---\nid: BMI-01\nstatus: Ready\n---\n\xff\xfe")

    validated = _run(["vault", "validate", str(vault), "--json"], env)
    claimed = _run(
        ["vault", "claim", str(vault), "BMI-01", "--agent", "codex", "--json"],
        env,
    )

    assert validated.exit_code != 0
    assert str(ticket) in validated.output
    assert claimed.exit_code != 0
    assert "unable to read ticket" in claimed.output


def test_dispatcher_signboard_ticket_round_trips_vault_validation_and_claim(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    ticket = vault / "agent-delivery" / "Ready" / "github-issue-3289.md"
    ticket.parent.mkdir(parents=True)
    ticket.write_text(
        _render_task(
            TaskRecord(
                task_id="github-issue-3289",
                issue_number=3289,
                title="Configure external Yggdrasil artifact vault",
                status="ready",
                priority="high",
                source_anchor_refs=["github:issue:3289"],
                created_at="2026-07-10T08:00:00Z",
                updated_at="2026-07-10T08:00:00Z",
            )
        ),
        encoding="utf-8",
    )

    validated = _run(["vault", "validate", str(vault), "--json"], env)
    claimed = _run(
        [
            "vault",
            "claim",
            str(vault),
            "github-issue-3289",
            "--agent",
            "codex",
            "--json",
        ],
        env,
    )

    assert validated.exit_code == 0, validated.output
    assert claimed.exit_code == 0, claimed.output


def test_queue_operations_reject_symlinked_vault_root_without_external_access(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    _ticket(outside)
    outside_sqlite = outside / "external.sqlite3"
    outside_sqlite.write_bytes(b"SQLite format 3\x00" + b"external-marker")
    alias = tmp_path / "shared-alias"
    try:
        alias.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    env = {
        "BUILDEROPS_VAULT_ROOT": str(alias),
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }

    validated = _run(["vault", "validate", str(alias), "--json"], env)
    claimed = _run(
        ["vault", "claim", str(alias), "BMI-01", "--agent", "codex", "--json"],
        env,
    )
    released = _run(
        ["vault", "release", str(alias), "BMI-01", "--agent", "codex", "--json"],
        env,
    )

    assert validated.exit_code != 0
    assert "root must not be a symlink" in validated.output
    assert claimed.exit_code != 0
    assert released.exit_code != 0
    assert outside_sqlite.read_bytes() == b"SQLite format 3\x00" + b"external-marker"
    assert not (outside / ".builderops").exists()


def test_queue_operations_reject_symlinked_vault_ancestor_without_external_access(
    tmp_path: Path,
) -> None:
    outside_parent = tmp_path / "outside-parent"
    outside_vault = outside_parent / "shared"
    _ticket(outside_vault)
    marker = outside_vault / "external-marker"
    marker.write_text("untouched", encoding="utf-8")
    alias_parent = tmp_path / "alias-parent"
    try:
        alias_parent.symlink_to(outside_parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    aliased_vault = alias_parent / "shared"
    env = {
        "BUILDEROPS_VAULT_ROOT": str(aliased_vault),
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }
    entries_before = {
        path.relative_to(outside_vault) for path in outside_vault.rglob("*")
    }

    initialized = _run(["vault", "init", str(aliased_vault), "--json"], env)
    validated = _run(["vault", "validate", str(aliased_vault), "--json"], env)
    claimed = _run(
        ["vault", "claim", str(aliased_vault), "BMI-01", "--agent", "codex", "--json"],
        env,
    )
    released = _run(
        ["vault", "release", str(aliased_vault), "BMI-01", "--agent", "codex", "--json"],
        env,
    )

    assert initialized.exit_code != 0
    assert "ancestor must not be a symlink" in initialized.output
    assert validated.exit_code != 0
    assert "ancestor must not be a symlink" in validated.output
    assert claimed.exit_code != 0
    assert released.exit_code != 0
    assert marker.read_text(encoding="utf-8") == "untouched"
    assert {
        path.relative_to(outside_vault) for path in outside_vault.rglob("*")
    } == entries_before
    assert not (outside_vault / ".builderops").exists()


def test_release_uses_payload_identity_and_rejects_blank_agents(tmp_path: Path) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    _ticket(vault)
    claims = vault / ".builderops" / "claims"
    claims.mkdir(parents=True)
    mismatched = claims / "BMI-01-codex-mismatch.json"
    mismatched.write_text(
        json.dumps(
            {
                "ticket_id": "BMI-02",
                "agent": "codex",
                "claimed_at": "2026-07-10T08:00:00Z",
                "expires_at": "2026-07-10T09:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    payload_match = claims / "non-authoritative-filename.json"
    payload_match.write_text(
        json.dumps(
            {
                "ticket_id": "BMI-01",
                "agent": "codex",
                "claimed_at": "2026-07-10T08:00:00Z",
                "expires_at": "2026-07-10T09:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    released = _run(
        ["vault", "release", str(vault), "BMI-01", "--agent", "codex", "--json"],
        env,
    )
    blank = _run(
        ["vault", "claim", str(vault), "BMI-01", "--agent", "   ", "--json"],
        env,
    )

    assert released.exit_code == 0, released.output
    assert mismatched.exists()
    assert not payload_match.exists()
    assert blank.exit_code != 0
    assert "agent must be non-empty" in blank.output
    assert list(claims.glob("*.json")) == [mismatched]


@pytest.mark.parametrize(
    ("claimed_at", "expires_at"),
    [
        ("2026-07-10T08:00:00", "2026-07-10T09:00:00Z"),
        ("2026-07-10T08:00:00Z", "2026-07-10T08:00:00Z"),
        ("2026-07-10T09:00:00Z", "2026-07-10T08:00:00Z"),
    ],
)
def test_queue_rejects_invalid_claim_time_windows(
    tmp_path: Path,
    claimed_at: str,
    expires_at: str,
) -> None:
    env = _env(tmp_path)
    vault = Path(env["BUILDEROPS_VAULT_ROOT"])
    _ticket(vault)
    claims = vault / ".builderops" / "claims"
    claims.mkdir(parents=True)
    invalid = claims / "BMI-01-codex-invalid.json"
    invalid.write_text(
        json.dumps(
            {
                "ticket_id": "BMI-01",
                "agent": "codex",
                "claimed_at": claimed_at,
                "expires_at": expires_at,
            }
        ),
        encoding="utf-8",
    )

    result = _run(["vault", "validate", str(vault), "--json"], env)

    assert result.exit_code != 0
    payload = json.loads(result.output.splitlines()[0])
    assert any(str(invalid) in error for error in payload["errors"])
