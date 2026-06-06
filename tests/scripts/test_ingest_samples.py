from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.dev import ingest_samples


def _write_seed(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "paths": {
                    "inbox_dir_rel": "Inbox",
                    "runtime_dir_rel": "System/Runtime",
                    "system_dir_rel": "System",
                },
                "ingest": {"active_vault_path": "vault"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_ingest_samples_seeds_ignored_default_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "sample.md").write_text("# Sample\n\nBody\n", encoding="utf-8")

    seed = tmp_path / "tests/fixtures/pkm_alpha/_system/settings/system-settings.yaml"
    _write_seed(seed)
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_RUNTIME_DIR_REL", raising=False)
    monkeypatch.setattr(ingest_samples, "ROOT", tmp_path)
    monkeypatch.setattr(ingest_samples, "DEFAULT_SETTINGS_SEED", seed)

    ingest_samples.main([str(samples)])

    settings = tmp_path / "vault/_system/settings/system-settings.yaml"
    imported = tmp_path / "vault/Inbox/Samples/sample.md"
    event_log = tmp_path / "vault/_system/events/ingest.log.jsonl"
    assert settings.is_file()
    assert imported.is_file()
    assert event_log.is_file()


def test_ingest_samples_does_not_seed_explicit_vault_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    samples = tmp_path / "samples"
    samples.mkdir()
    explicit_vault = tmp_path / "external-vault"
    monkeypatch.setenv("VAULT_ROOT", str(explicit_vault))

    with pytest.raises(SystemExit, match="Missing system settings for explicit VAULT_ROOT"):
        ingest_samples.main([str(samples)])

    assert not (explicit_vault / "_system/settings/system-settings.yaml").exists()
