from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root
from app.builderops.vault_queue import VaultQueueError, claim_ticket, import_dispatcher_tasks


def _run_builderops(args: list[str]):
    return CliRunner().invoke(
        builderops_standalone_root,
        ["builderops", *args],
        catch_exceptions=False,
    )


def _write_ticket(root: Path, status: str = "Ready", ticket_id: str = "ticket-2686") -> Path:
    path = root / "agent-delivery" / status / f"{ticket_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                f'id: "{ticket_id}"',
                'title: "GraphQL exhaustion fix"',
                f'status: "{status}"',
                "github_issue: 2686",
                'github_pr: ""',
                'priority: "high"',
                'agent_state: "Idle"',
                'owner: ""',
                'labels: ["agent:ready"]',
                'updated_at: "2026-07-09T19:30:00Z"',
                "---",
                "",
                "## Context",
                "",
                "## Receipts",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_vault_init_writes_contract_and_directories(tmp_path: Path) -> None:
    result = _run_builderops(["vault", "init", str(tmp_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["root"] == str(tmp_path)
    assert (
        (tmp_path / "AGENTS.md")
        .read_text(encoding="utf-8")
        .startswith("# Builder Ops Vault Agent Contract")
    )
    assert (tmp_path / "agent-delivery" / "Ready").is_dir()
    assert (tmp_path / ".builderops" / "claims").is_dir()
    assert (tmp_path / ".builderops" / "locks").is_dir()


def test_vault_validate_requires_folder_and_yaml_status_match(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    _write_ticket(tmp_path, status="Ready")

    ok = _run_builderops(["vault", "validate", str(tmp_path), "--json"])
    assert ok.exit_code == 0
    assert json.loads(ok.output)["ok"] is True

    path = tmp_path / "agent-delivery" / "Ready" / "ticket-2686.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace('status: "Ready"', 'status: "Blocked"'),
        encoding="utf-8",
    )
    bad = _run_builderops(["vault", "validate", str(tmp_path), "--json"])
    assert bad.exit_code != 0
    assert '"ok": false' in bad.output
    assert "does not match" in bad.output


def test_vault_validate_reports_malformed_ticket(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    path = tmp_path / "agent-delivery" / "Ready" / "broken.md"
    path.write_text("no frontmatter\n", encoding="utf-8")

    result = _run_builderops(["vault", "validate", str(tmp_path), "--json"])
    assert result.exit_code != 0
    assert '"ok": false' in result.output
    assert "missing YAML frontmatter" in result.output


def test_vault_validate_fails_loudly_when_not_initialized(tmp_path: Path) -> None:
    result = _run_builderops(["vault", "validate", str(tmp_path), "--json"])

    assert result.exit_code != 0
    payload = json.loads(result.output.split("\nError:", 1)[0])
    assert payload["ok"] is False
    assert any("missing AGENTS.md" in error for error in payload["errors"])


def test_vault_validate_rejects_wrong_contract_and_incomplete_schema(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    (tmp_path / "AGENTS.md").write_text("# unrelated\n", encoding="utf-8")
    ticket = _write_ticket(tmp_path, status="Ready")
    ticket.write_text(
        ticket.read_text(encoding="utf-8").replace('priority: "high"\n', ""),
        encoding="utf-8",
    )

    result = _run_builderops(["vault", "validate", str(tmp_path), "--json"])

    assert result.exit_code != 0
    payload = json.loads(result.output.split("\nError:", 1)[0])
    assert any("invalid Builder Ops Vault agent contract" in error for error in payload["errors"])
    assert any("missing required fields: priority" in error for error in payload["errors"])


def test_vault_next_claim_release_round_trip(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    _write_ticket(tmp_path, status="Ready")

    next_result = _run_builderops(["vault", "next", str(tmp_path), "--json"])
    assert json.loads(next_result.output)["ticket"]["meta"]["id"] == "ticket-2686"

    claim = _run_builderops(
        [
            "vault",
            "claim",
            str(tmp_path),
            "ticket-2686",
            "--agent",
            "codex",
            "--session",
            "session-1",
            "--json",
        ]
    )
    assert claim.exit_code == 0
    claim_payload = json.loads(claim.output)
    assert claim_payload["claim"]["agent"] == "codex"
    assert claim_payload["ticket"]["meta"]["status"] == "In Progress"
    assert (tmp_path / "agent-delivery" / "In Progress" / "ticket-2686.md").exists()
    assert not (tmp_path / "agent-delivery" / "Ready" / "ticket-2686.md").exists()
    claim_path = tmp_path / ".builderops" / "claims" / "ticket-2686.json"
    assert claim_path.exists()

    valid = _run_builderops(["vault", "validate", str(tmp_path), "--json"])
    assert valid.exit_code == 0

    empty_next = _run_builderops(["vault", "next", str(tmp_path), "--json"])
    assert json.loads(empty_next.output)["ticket"] is None

    release = _run_builderops(
        ["vault", "release", str(tmp_path), "ticket-2686", "--agent", "codex", "--json"]
    )
    assert release.exit_code == 0
    assert not claim_path.exists()
    assert json.loads(release.output)["ticket"]["meta"]["agent_state"] == "Idle"


def test_vault_next_prioritizes_high_value_work(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    low = _write_ticket(tmp_path, status="Ready", ticket_id="a-low")
    _write_ticket(tmp_path, status="Ready", ticket_id="z-high")
    low.write_text(
        low.read_text(encoding="utf-8").replace('priority: "high"', 'priority: "low"'),
        encoding="utf-8",
    )

    result = _run_builderops(["vault", "next", str(tmp_path), "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output)["ticket"]["meta"]["id"] == "z-high"


def test_vault_import_dispatcher_is_dry_run_idempotent_and_skips_active(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    tasks = [
        {
            "task_id": "github-issue-100",
            "issue_number": 100,
            "title": 'Ready "high" work',
            "status": "ready",
            "priority": "high",
            "source_anchor_refs": ["docs/ROADMAP.md :: TEST"],
            "linked_pr": None,
            "sync_state": {"labels": ["agent:ready"]},
            "updated_at": "2026-07-10T00:00:00Z",
        },
        {
            "task_id": "github-issue-101",
            "issue_number": 101,
            "title": "Already active",
            "status": "claimed",
            "priority": "high",
            "source_anchor_refs": [],
            "updated_at": "2026-07-10T00:00:00Z",
        },
    ]

    dry_run = import_dispatcher_tasks(tmp_path, tasks)
    assert dry_run["apply"] is False
    assert len(dry_run["planned"]) == 1
    assert not (tmp_path / "agent-delivery" / "Ready" / "github-issue-100.md").exists()
    assert any("active dispatcher work" in item["reason"] for item in dry_run["skipped"])

    applied = import_dispatcher_tasks(tmp_path, tasks, apply=True)
    assert len(applied["imported"]) == 1
    ticket = tmp_path / "agent-delivery" / "Ready" / "github-issue-100.md"
    assert ticket.exists()
    assert 'title: "Ready \\"high\\" work"' in ticket.read_text(encoding="utf-8")

    repeated = import_dispatcher_tasks(tmp_path, tasks, apply=True)
    assert repeated["imported"] == []
    assert any(item["reason"] == "vault ticket already exists" for item in repeated["skipped"])


def test_vault_claim_fails_when_active_claim_exists(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    _write_ticket(tmp_path, status="Ready")

    first = _run_builderops(
        ["vault", "claim", str(tmp_path), "ticket-2686", "--agent", "codex", "--json"]
    )
    assert first.exit_code == 0

    second = _run_builderops(
        ["vault", "claim", str(tmp_path), "ticket-2686", "--agent", "claude", "--json"]
    )
    assert second.exit_code != 0
    assert "already claimed by codex" in second.output


def test_vault_next_reports_malformed_claim_without_traceback(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    _write_ticket(tmp_path, status="Ready")
    claim_path = tmp_path / ".builderops" / "claims" / "ticket-2686.json"
    claim_path.write_text('{"ticket_id": "ticket-2686"}\n', encoding="utf-8")

    result = _run_builderops(["vault", "next", str(tmp_path), "--json"])

    assert result.exit_code != 0
    assert "invalid claim file" in result.output
    assert "Traceback" not in result.output


def test_vault_claim_rejects_nonpositive_ttl_and_nonready_ticket(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    _write_ticket(tmp_path, status="Ready", ticket_id="ready-ticket")
    _write_ticket(tmp_path, status="Backlog", ticket_id="backlog-ticket")

    bad_ttl = _run_builderops(
        [
            "vault",
            "claim",
            str(tmp_path),
            "ready-ticket",
            "--agent",
            "codex",
            "--ttl-minutes",
            "0",
            "--json",
        ]
    )
    assert bad_ttl.exit_code != 0
    assert "greater than zero" in bad_ttl.output

    nonready = _run_builderops(
        ["vault", "claim", str(tmp_path), "backlog-ticket", "--agent", "codex", "--json"]
    )
    assert nonready.exit_code != 0
    assert "only Ready tickets" in nonready.output


def test_vault_renew_extends_only_the_owners_active_claim(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    _write_ticket(tmp_path, status="Ready")
    claim = _run_builderops(
        [
            "vault",
            "claim",
            str(tmp_path),
            "ticket-2686",
            "--agent",
            "codex",
            "--ttl-minutes",
            "10",
            "--json",
        ]
    )
    original_expiry = json.loads(claim.output)["claim"]["expires_at"]

    wrong_owner = _run_builderops(
        ["vault", "renew", str(tmp_path), "ticket-2686", "--agent", "claude", "--json"]
    )
    assert wrong_owner.exit_code != 0
    assert "claimed by codex, not claude" in wrong_owner.output

    renewed = _run_builderops(
        [
            "vault",
            "renew",
            str(tmp_path),
            "ticket-2686",
            "--agent",
            "codex",
            "--ttl-minutes",
            "120",
            "--json",
        ]
    )
    assert renewed.exit_code == 0
    assert json.loads(renewed.output)["claim"]["expires_at"] > original_expiry


def test_vault_stale_claim_takeover_requires_flag_and_records_receipt(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    path = _write_ticket(tmp_path, status="Ready")
    claim_dir = tmp_path / ".builderops" / "claims"
    claim_dir.mkdir(parents=True, exist_ok=True)
    (claim_dir / "ticket-2686.json").write_text(
        json.dumps(
            {
                "ticket_id": "ticket-2686",
                "agent": "codex",
                "claimed_at": "2020-01-01T00:00:00Z",
                "expires_at": "2020-01-01T00:01:00Z",
                "session": "old",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    blocked = _run_builderops(
        ["vault", "claim", str(tmp_path), "ticket-2686", "--agent", "claude", "--json"]
    )
    assert blocked.exit_code != 0
    assert "pass --takeover-stale" in blocked.output

    takeover = _run_builderops(
        [
            "vault",
            "claim",
            str(tmp_path),
            "ticket-2686",
            "--agent",
            "claude",
            "--takeover-stale",
            "--json",
        ]
    )
    assert takeover.exit_code == 0
    assert not path.exists()
    content = (tmp_path / "agent-delivery" / "In Progress" / "ticket-2686.md").read_text(
        encoding="utf-8"
    )
    assert "stale claim takeover by claude" in content
    assert "claimed by claude" in content


def test_vault_active_claim_blocks_other_actor_mutations(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    _write_ticket(tmp_path, status="Ready")
    claimed = _run_builderops(
        ["vault", "claim", str(tmp_path), "ticket-2686", "--agent", "codex", "--json"]
    )
    assert claimed.exit_code == 0

    move = _run_builderops(
        [
            "vault",
            "move",
            str(tmp_path),
            "ticket-2686",
            "Review",
            "--actor",
            "claude",
            "--json",
        ]
    )
    assert move.exit_code != 0
    assert "claimed by codex, not claude" in move.output

    note = _run_builderops(
        [
            "vault",
            "note",
            str(tmp_path),
            "ticket-2686",
            "unauthorized",
            "--actor",
            "claude",
            "--json",
        ]
    )
    assert note.exit_code != 0
    assert "claimed by codex, not claude" in note.output


def test_vault_blocked_transition_releases_claim_and_validates(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    _write_ticket(tmp_path, status="Ready")
    claim = _run_builderops(
        ["vault", "claim", str(tmp_path), "ticket-2686", "--agent", "codex", "--json"]
    )
    assert claim.exit_code == 0

    moved = _run_builderops(
        [
            "vault",
            "move",
            str(tmp_path),
            "ticket-2686",
            "Blocked",
            "--actor",
            "codex",
            "--json",
        ]
    )
    assert moved.exit_code == 0
    assert not (tmp_path / ".builderops" / "claims" / "ticket-2686.json").exists()
    payload = json.loads(moved.output)["ticket"]
    assert payload["meta"]["agent_state"] == "Idle"
    assert payload["meta"]["owner"] == ""
    valid = _run_builderops(["vault", "validate", str(tmp_path), "--json"])
    assert valid.exit_code == 0


def test_vault_claim_serializes_competing_agents(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    _write_ticket(tmp_path, status="Ready")

    def attempt(agent: str) -> str:
        try:
            claim_ticket(tmp_path, "ticket-2686", agent=agent)
        except VaultQueueError:
            return "blocked"
        return "claimed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["codex", "claude"]))

    assert sorted(outcomes) == ["blocked", "claimed"]


def test_vault_move_keeps_folder_and_yaml_in_sync(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    _write_ticket(tmp_path, status="Ready")

    moved = _run_builderops(
        [
            "vault",
            "move",
            str(tmp_path),
            "ticket-2686",
            "Blocked",
            "--actor",
            "codex",
            "--json",
        ]
    )
    assert moved.exit_code == 0
    target = tmp_path / "agent-delivery" / "Blocked" / "ticket-2686.md"
    assert target.exists()
    assert not (tmp_path / "agent-delivery" / "Ready" / "ticket-2686.md").exists()
    assert 'status: "Blocked"' in target.read_text(encoding="utf-8")


def test_vault_note_appends_receipt(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    path = _write_ticket(tmp_path, status="Ready")

    result = _run_builderops(
        [
            "vault",
            "note",
            str(tmp_path),
            "ticket-2686",
            "blocked on auth decision",
            "--actor",
            "claude",
            "--json",
        ]
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["ticket"]["meta"]["updated_at"] != "2026-07-09T19:30:00Z"
    assert "note by claude: blocked on auth decision" in path.read_text(encoding="utf-8")


def test_vault_mutation_preserves_quoted_unicode_title(tmp_path: Path) -> None:
    _run_builderops(["vault", "init", str(tmp_path), "--json"])
    path = _write_ticket(tmp_path, status="Ready")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'title: "GraphQL exhaustion fix"',
            'title: "Fixa \\"dyr\\" kö — nu"',
        ),
        encoding="utf-8",
    )

    result = _run_builderops(
        ["vault", "note", str(tmp_path), "ticket-2686", "verified", "--actor", "codex", "--json"]
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["ticket"]["meta"]["title"] == 'Fixa "dyr" kö — nu'
    assert 'title: "Fixa \\"dyr\\" kö — nu"' in path.read_text(encoding="utf-8")
