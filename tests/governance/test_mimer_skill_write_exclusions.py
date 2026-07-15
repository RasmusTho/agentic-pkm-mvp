from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_sources_zone_is_excluded_from_mimer_app_agent_writes() -> None:
    governed_boundary = (
        ROOT / ".codex/skills/mimer-governed-boundary/SKILL.md"
    ).read_text(encoding="utf-8")
    vault_workspace = (
        ROOT / ".codex/skills/mimer-vault-workspace/SKILL.md"
    ).read_text(encoding="utf-8")

    settings_named_exclusion = (
        "The Sources zone (`<sources_dir_rel>/`, default `Sources/`)"
    )
    direct_write_prohibition = "never a direct app-agent write target"

    assert settings_named_exclusion in governed_boundary
    assert direct_write_prohibition in governed_boundary
    assert settings_named_exclusion in vault_workspace
    assert direct_write_prohibition in vault_workspace
