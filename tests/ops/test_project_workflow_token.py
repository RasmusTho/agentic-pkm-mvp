from pathlib import Path

import yaml


PROJECT_WORKFLOWS = (
    Path(".github/workflows/project-status-reconcile.yml"),
    Path(".github/workflows/project-pr-opened.yml"),
    Path(".github/workflows/project-pr-stage-change.yml"),
)


def test_project_workflows_use_app_installation_token() -> None:
    for path in PROJECT_WORKFLOWS:
        workflow = path.read_text(encoding="utf-8")
        workflow_data = yaml.safe_load(workflow)

        assert "actions/create-github-app-token@v3" in workflow
        assert "id: project-app-config" in workflow
        assert "PROJECT_APP_ID: ${{ secrets.PROJECT_APP_ID }}" in workflow
        assert "PROJECT_APP_PRIVATE_KEY: ${{ secrets.PROJECT_APP_PRIVATE_KEY }}" in workflow
        assert "if: ${{ steps.project-app-config.outputs.configured == 'true' }}" in workflow
        assert "app-id: ${{ secrets.PROJECT_APP_ID }}" in workflow
        assert "private-key: ${{ secrets.PROJECT_APP_PRIVATE_KEY }}" in workflow
        assert "owner: Yggdrasil-PKM" in workflow
        assert "permission-organization-projects: write" in workflow
        assert "permission-issues: read" in workflow
        assert "permission-pull-requests: read" in workflow
        assert "GH_TOKEN: ${{ steps.project-app-token.outputs.token || secrets.GITHUB_TOKEN }}" in workflow
        assert "REPO_GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in workflow
        assert "--owner \"Yggdrasil-PKM\"" in workflow
        assert "PROJECT_TOKEN" not in workflow

        for job in workflow_data["jobs"].values():
            steps = job["steps"]
            config_step = next(step for step in steps if step.get("id") == "project-app-config")
            token_step = next(step for step in steps if step.get("id") == "project-app-token")
            projection_step = next(
                step
                for step in steps
                if step.get("env", {}).get("GH_TOKEN")
                == "${{ steps.project-app-token.outputs.token || secrets.GITHUB_TOKEN }}"
            )

            assert config_step["env"] == {
                "PROJECT_APP_ID": "${{ secrets.PROJECT_APP_ID }}",
                "PROJECT_APP_PRIVATE_KEY": "${{ secrets.PROJECT_APP_PRIVATE_KEY }}",
            }
            assert 'configured=false' in config_step["run"]
            assert token_step["if"] == "${{ steps.project-app-config.outputs.configured == 'true' }}"
            assert token_step["uses"] == "actions/create-github-app-token@v3"
            assert token_step["with"]["app-id"] == "${{ secrets.PROJECT_APP_ID }}"
            assert token_step["with"]["private-key"] == "${{ secrets.PROJECT_APP_PRIVATE_KEY }}"
            assert token_step["with"]["owner"] == "Yggdrasil-PKM"
            assert token_step["with"]["permission-organization-projects"] == "write"
            assert projection_step["env"]["GH_TOKEN"].endswith("secrets.GITHUB_TOKEN }}")
            assert projection_step["env"]["REPO_GH_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"


def test_governance_project_owner_is_the_organization_target() -> None:
    governance = yaml.safe_load(
        Path(".github/github-governance.yml").read_text(encoding="utf-8")
    )
    assert governance["project"]["owner"] == "Yggdrasil-PKM"
