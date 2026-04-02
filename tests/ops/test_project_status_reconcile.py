from pathlib import Path

from scripts.reconcile_project_status import desired_pr_status, load_governance_project_name


def test_desired_pr_status_open_pr_is_in_progress() -> None:
    assert desired_pr_status({"state": "OPEN", "mergedAt": None}, None) == "In Progress"


def test_desired_pr_status_closed_unmerged_pr_is_done() -> None:
    assert desired_pr_status({"state": "CLOSED", "mergedAt": None}, None) == "Done"


def test_desired_pr_status_explicit_status_wins() -> None:
    assert (
        desired_pr_status({"state": "CLOSED", "mergedAt": None}, "Review")
        == "Review"
    )


def test_load_governance_project_name_reads_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    governance_dir = Path(".github")
    governance_dir.mkdir(parents=True)
    governance_file = governance_dir / "github-governance.yml"
    governance_file.write_text("project:\n  name: Custom Project\n", encoding="utf-8")
    assert load_governance_project_name() == "Custom Project"


def test_load_governance_project_name_falls_back_when_file_missing(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GOVERNANCE_PROJECT_NAME", raising=False)
    assert load_governance_project_name() == "Agent Delivery Control Plane"


def test_load_governance_project_name_uses_env_override_when_file_missing(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOVERNANCE_PROJECT_NAME", "Override Project")
    assert load_governance_project_name() == "Override Project"
