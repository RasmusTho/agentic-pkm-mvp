from __future__ import annotations

import ast
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _signboard_imports(source: str, *, filename: str = "<source>") -> set[str]:
    """Return every import form that reaches the Signboard projection module."""
    tree = ast.parse(source, filename=filename)
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "app.dispatcher.signboard":
                imports.update(alias.name for alias in node.names)
            elif node.module == "app.dispatcher":
                imports.update(alias.name for alias in node.names if alias.name == "signboard")
            elif node.level and node.module == "signboard":
                imports.update(alias.name for alias in node.names)
            elif node.level and node.module is None:
                imports.update(alias.name for alias in node.names if alias.name == "signboard")
        elif isinstance(node, ast.Import):
            imports.update(
                alias.name for alias in node.names if alias.name == "app.dispatcher.signboard"
            )

    return imports


def test_active_pickup_contract_is_label_only() -> None:
    agents = _read("AGENTS.md")
    issue_to_code = _read(".codex/skills/issue-to-code/SKILL.md")
    deliver_issue_set = _read(".codex/skills/deliver-issue-set/SKILL.md")
    dev_workflow = _read("docs/development/DEV_WORKFLOW.md")
    labels = _read(".codex/skills/_shared/LABEL_TAXONOMY.md")

    assert "strictly valid `agent:ready`" in agents
    assert "without requiring GitHub Project Status" in agents
    assert "Work only from GitHub Issues labeled `agent:ready`" in issue_to_code
    assert "Project Status is not a pickup precondition" in issue_to_code
    assert "Project Status is not a dispatch precondition" in deliver_issue_set
    assert "Project Status is not a pickup gate" in dev_workflow
    assert "without requiring Project Status" in labels
    assert "label removal + claimant receipt" in issue_to_code

    canonical_pickup_contracts = (
        agents,
        issue_to_code,
        deliver_issue_set,
        dev_workflow,
        _read(".codex/skills/README.md"),
        _read("docs/development/BUILDER_SYSTEM_PROCESS_MAP.md"),
    )
    forbidden_gates = (
        "Issue -> Project -> Agent",
        "both `Status=Ready` and labeled `agent:ready`",
        "`agent:ready` + Status=Ready",
        "Status=Ready qualifies pickup",
    )
    for contract in canonical_pickup_contracts:
        for phrase in forbidden_gates:
            assert phrase not in contract


def test_ready_producers_do_not_require_project_status() -> None:
    producers = (
        _read(".codex/skills/docs-to-issue/SKILL.md"),
        _read(".codex/skills/feature-breakdown/SKILL.md"),
        _read(".codex/skills/learning-to-issue/SKILL.md"),
        _read(".codex/skills/bug-to-issue/SKILL.md"),
        _read(".codex/skills/issue-maintenance-change-control/SKILL.md"),
    )

    for contract in producers:
        assert "Use `agent:ready` only with `Status=Ready`" not in contract
        assert "can label as `agent:ready` with `Status=Ready` only" not in contract
        assert "project" in contract.lower()
        assert "optional" in contract.lower()


def test_governance_config_does_not_require_project_status_for_pickup() -> None:
    governance = _read(".github/github-governance.yml")

    assert "queue-eligible work when Status=Ready" not in governance
    assert "agents_only_pick: label:agent:ready + status:Ready" not in governance
    assert "strictly validated" in governance
    assert "Project Status" in governance
    assert "optional" in governance


def test_worker_adapter_accepts_label_only_dispatch() -> None:
    adapter = _read(".codex/agents/slice-implementer.toml")
    roles = _read("docs/development/BUILDER_SUBAGENT_ROLES.md")

    assert "Status=Ready and labeled agent:ready" not in adapter
    assert "strictly validated issue labeled agent:ready" in adapter
    assert "Project Status is not a pickup gate" in adapter
    assert "`Ready` + `agent:ready`" not in roles
    assert "strictly validated `agent:ready`" in roles
    assert "Project Status is optional projection" in roles


def test_builderops_authority_roles_are_explicit() -> None:
    dispatcher = _read("docs/AGENT_ISSUE_DISPATCHER.md")
    architecture = _read("docs/ARCHITECTURE.md")
    process_map = _read("docs/development/BUILDER_SYSTEM_PROCESS_MAP.md")

    for text in (dispatcher, architecture, process_map):
        assert "GitHub Issues / PRs / CI" in text
        assert "Dispatcher SQLite" in text
        assert "external BuilderOps Vault" in text
        assert "Project" in text
        assert "projection" in text
    assert "GitHub Project v2 is the delivery state machine" not in architecture
    assert "Status=Ready qualifies pickup" not in process_map
    assert "labels, Project states, `Verify:` markers" not in process_map
    assert "labels, Project status, skill routing" not in process_map


def test_external_vault_separates_authoritative_leases_from_advisory_claims() -> None:
    contract = _read(
        "docs/BUILDEROPS_MODEL_INQUIRY/EXTERNAL_BUILDEROPS_VAULT_CONFIGURATION.md"
    )

    assert "shared Markdown artifacts" in contract
    assert "TTL-based advisory claim signals" in contract
    assert "local authoritative dispatcher leases" in contract
    assert "without creating SQLite files or provider credentials" in contract
    assert "exclusive distributed" in contract


def test_pickup_paths_never_read_signboard_projection() -> None:
    pickup_paths = (
        "app/dispatcher/queue.py",
        "app/dispatcher/sync_github.py",
        "app/dispatcher/leases.py",
    )

    for path in pickup_paths:
        source = _read(path)
        assert "SIGNBOARD_ROOT" not in source
        assert ".read_text(" not in source
        assert ".read_bytes(" not in source
        assert ".open(" not in source
        # Pickup paths may share only pure dispatcher status/column helpers;
        # board export and card-reading helpers remain projection-layer code.
        assert _signboard_imports(source, filename=path) <= {
            "canonical_status",
            "column_for_status",
        }


def test_signboard_root_consumers_are_projection_layer_only() -> None:
    signboard_root_consumers = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "app").rglob("*.py")
        if "SIGNBOARD_ROOT" in path.read_text(encoding="utf-8")
    }

    assert signboard_root_consumers == {
        "app/api/routes/signboard.py",
        "app/ops/builderops_startup.py",
    }

    # CLI may export the projection, but no command may consume the operator
    # board-root setting as pickup input.
    assert "SIGNBOARD_ROOT" not in _read("app/dispatcher/cli.py")
    assert _signboard_imports(_read("app/dispatcher/cli.py"), filename="app/dispatcher/cli.py") == {
        "NoActiveVaultError",
        # The board-ownership refusal (#4370) surfaces as a non-zero exit, not
        # as a traceback; that is projection-layer error handling, not pickup
        # input.
        "SignboardStoreOwnershipError",
        "default_signboard_root",
        "export_signboard",
        "validate_signboard",
    }


@pytest.mark.parametrize(
    "source",
    (
        "from app.dispatcher.signboard import export_signboard\n",
        "import app.dispatcher.signboard\n",
        "from app.dispatcher import signboard\n",
        "async def pickup():\n    from app.dispatcher.signboard import export_signboard\n",
        "from .signboard import export_signboard\n",
        "from . import signboard\n",
    ),
)
def test_pickup_import_guard_rejects_every_projection_import_form(source: str) -> None:
    imports = _signboard_imports(source, filename="app/dispatcher/queue.py")

    assert imports
    assert not imports <= {"canonical_status", "column_for_status"}


def test_signboard_documented_as_projection_not_pickup_input() -> None:
    dispatcher = _read("docs/AGENT_ISSUE_DISPATCHER.md")

    assert "Signboard files are generated" in dispatcher
    assert "should not be treated as authoritative input" in dispatcher
    assert "projection state only" in dispatcher
