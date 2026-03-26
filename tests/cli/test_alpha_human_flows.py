from __future__ import annotations

import importlib
import shutil
import textwrap
from pathlib import Path

from click.testing import CliRunner

from app.cli import cli
from app.retrieval.hybrid import get_store
from app.services.note_log import note_log_path
from scripts.yaml_roundtrip import load_frontmatter

alpha_human_flows_module = importlib.import_module("app.cli.alpha_human_flows")
FIXTURE_VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "vault_alpha"


def _base_env(tmp_path: Path) -> dict[str, str]:
    return {
        "LLM_PROVIDER": "mock",
        "LLM_MOCK_RESPONSE": "Mock response [#1]",
        "INDEX_OUTBOX_PATH": str(tmp_path / "outbox.jsonl"),
        "STORE_BACKEND": "memory",
    }


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "Index").mkdir(parents=True, exist_ok=True)
    (vault / "Projects").mkdir(parents=True, exist_ok=True)
    sample = vault / "Index" / "zones.md"
    sample.write_text(
        textwrap.dedent(
            """
            # Zones overview
            Explain briefly how Active Warm Cold zones work in my system.
            Active zone, Warm zone, Cold zone in my system.
            Mimer module handles the knowledge vault.
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    filler = vault / "Projects" / "other.md"
    filler.write_text("# Other project\nThis note is unrelated.\n", encoding="utf-8")
    return vault


def _copy_fixture_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, vault)
    return vault


def _run_cli(vault: Path, tmp_path: Path, extra: list[str] | None = None):
    args = ["alpha-human-flows", "--vault-root", str(vault), "--sample-size", "2"]
    if extra:
        args.extend(extra)
    runner = CliRunner()
    env = _base_env(tmp_path)
    return runner.invoke(cli, args, env=env)


def test_alpha_human_flows_creates_test_note_and_uuid(tmp_path: Path) -> None:
    get_store().set_documents([])
    vault = _make_vault(tmp_path)

    result = _run_cli(vault, tmp_path)

    assert result.exit_code == 0, result.output
    test_note = vault / "Test" / "Alpha-HumanFlows.md"
    assert test_note.exists()
    frontmatter, body = load_frontmatter(test_note.read_text(encoding="utf-8"))
    assert str(frontmatter.get("uuid") or "").strip()
    assert "%% AI:Start %%" in body
    assert "## AI-instruktion" in body
    lines = body.splitlines()
    fence_lines = [ln for ln in lines if ln.strip().startswith("%%") and "ai" in ln.lower()]
    assert fence_lines, "Expected an AI fence line"
    intro_idx = lines.index("Alpha Human Flows test note for orchestration.")
    fence_idx = lines.index(fence_lines[0])
    assert fence_idx > intro_idx
    assert "%%" not in lines[intro_idx].strip(), "Intro line must not include AI fence"


def test_alpha_human_flows_is_idempotent(tmp_path: Path) -> None:
    get_store().set_documents([])
    vault = _make_vault(tmp_path)

    first = _run_cli(vault, tmp_path)
    assert first.exit_code == 0, first.output
    test_note = vault / "Test" / "Alpha-HumanFlows.md"
    fm1, body1 = load_frontmatter(test_note.read_text(encoding="utf-8"))
    uuid1 = fm1.get("uuid")

    second = _run_cli(vault, tmp_path)
    assert second.exit_code == 0, second.output
    fm2, body2 = load_frontmatter(test_note.read_text(encoding="utf-8"))
    uuid2 = fm2.get("uuid")

    assert uuid1 == uuid2
    assert body2.count("## AI-instruktion") == 1
    assert fm2.get("review_state") == "reviewed"
    assert fm2.get("maturity") == "evergreen"
    assert body1 == body2 or body2.endswith(body1)  # allow trailing newline normalization


def test_alpha_human_flows_dry_run_makes_no_changes(tmp_path: Path) -> None:
    get_store().set_documents([])
    vault = _make_vault(tmp_path)
    sample = vault / "Index" / "zones.md"
    before = sample.read_text(encoding="utf-8")

    result = _run_cli(vault, tmp_path, extra=["--dry-run"])

    assert result.exit_code == 0, result.output
    test_note = vault / "Test" / "Alpha-HumanFlows.md"
    assert not test_note.exists()
    after = sample.read_text(encoding="utf-8")
    assert before == after
    outbox = Path(_base_env(tmp_path)["INDEX_OUTBOX_PATH"])
    assert not outbox.exists()


def test_alpha_human_flows_reports_mirror_path(tmp_path: Path) -> None:
    get_store().set_documents([])
    vault = _make_vault(tmp_path)

    result = _run_cli(vault, tmp_path)

    assert result.exit_code == 0, result.output
    test_note = vault / "Test" / "Alpha-HumanFlows.md"
    frontmatter, _ = load_frontmatter(test_note.read_text(encoding="utf-8"))
    note_uuid = str(frontmatter.get("uuid") or "").strip()
    expected_mirror = note_log_path(note_uuid, Path("Test/Alpha-HumanFlows.md"))
    assert str(expected_mirror) in result.output


def test_alpha_human_flows_runs_ask_flow(tmp_path: Path) -> None:
    get_store().set_documents([])
    vault = _make_vault(tmp_path)

    result = _run_cli(vault, tmp_path)

    assert result.exit_code == 0, result.output
    assert 'ASK: "What does the Alpha Human Flows test note say?"' in result.output
    assert "ASK: \"Explain briefly how Active / Warm / Cold zones work in my system.\"" in result.output
    assert "SOURCES:" in result.output
    assert "Test/Alpha-HumanFlows.md" in result.output or "Index/zones.md" in result.output
    docs = get_store().all()
    assert all("The Earth has two moons" not in doc.text for doc in docs)


def test_alpha_human_flows_explain_only(tmp_path: Path) -> None:
    get_store().set_documents([])
    vault = _make_vault(tmp_path)
    test_note = vault / "Test" / "Alpha-HumanFlows.md"

    result = _run_cli(vault, tmp_path, extra=["--explain-only"])

    assert result.exit_code == 0, result.output
    output = result.output
    for letter in ("A", "B", "C", "D", "E", "F"):
        assert f"{letter}:" in output
    assert "[ ] A: Sample ingest" in output
    assert not test_note.exists()
    outbox = Path(_base_env(tmp_path)["INDEX_OUTBOX_PATH"])
    assert not outbox.exists()


def test_alpha_human_flows_writes_test_note_via_knowledge_port(tmp_path: Path, monkeypatch) -> None:
    get_store().set_documents([])
    vault = _make_vault(tmp_path)
    writes: list[str] = []

    def _fake_write(path: Path, content: str, *, vault_root: Path | None = None):  # type: ignore[no-untyped-def]
        resolved_root = (vault_root or vault).resolve()
        rel = Path(path).resolve().relative_to(resolved_root).as_posix()
        writes.append(rel)
        target = (resolved_root / rel).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return None

    monkeypatch.setattr(alpha_human_flows_module, "write_note_from_absolute", _fake_write)
    result = _run_cli(vault, tmp_path)
    assert result.exit_code == 0, result.output
    assert "Test/Alpha-HumanFlows.md" in writes


def test_alpha_human_flows_runs_against_fixture_vault_alpha(tmp_path: Path) -> None:
    get_store().set_documents([])
    vault = _copy_fixture_vault(tmp_path)

    result = _run_cli(vault, tmp_path)

    assert result.exit_code == 0, result.output
    assert 'ASK: "What does the Alpha Human Flows test note say?"' in result.output
    assert "SOURCES:" in result.output
    assert "Test/Alpha-HumanFlows.md" in result.output or "Concepts/ExistingUUID.md" in result.output

    test_note = vault / "Test" / "Alpha-HumanFlows.md"
    frontmatter, body = load_frontmatter(test_note.read_text(encoding="utf-8"))
    assert frontmatter.get("uuid") == "22222222-2222-2222-2222-222222222222"
    assert frontmatter.get("review_state") == "reviewed"
    assert frontmatter.get("maturity") == "evergreen"
    assert "Alpha Human Flows test note for orchestration." in body


# Coverage gaps: Flow A sample selection errors not exercised; mirror file creation not asserted (path only);
# ASK output content not validated beyond source presence; ingestion error handling paths not covered.
