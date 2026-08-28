from __future__ import annotations

from app.cli.settings_explain import build_settings_explain_payload
from app.settings import compiler
from app.settings import runtime
from app.settings.ingestion import (
    STATE_NO_VAULT,
    SettingsIngestionState,
    get_settings_ingestion_state,
    reset_settings_ingestion_state,
)
from app.settings.models import SettingsBundle, TTSSettings
from app.tts.config import load_tts_config
from app.tts.planning import build_tts_plan

def test_voice_resolves_from_settings_on_synthesis_path(monkeypatch, tmp_path) -> None:
    vault_root = tmp_path / "vault"
    settings_dir = vault_root / "settings"
    settings_dir.mkdir(parents=True)
    (settings_dir / "tts.md").write_text(
        "# TTS\n\n```yaml settings\nvoices:\n  sv: sv_SE-nst-medium\n  en_us: af_heart\n  en_gb: bf_emma\nfallback_policy: local_only\n```\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(compiler, "RUNTIME", tmp_path / "runtime" / "settings")
    bundle = compiler.compile_all(vault_root=vault_root)
    monkeypatch.setattr("app.tts.config.get_settings_bundle", lambda: bundle)
    monkeypatch.setattr("app.cli.settings_explain.get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(
        "app.cli.settings_explain.get_settings_ingestion_state",
        lambda: SettingsIngestionState(state="ok", source="vault", tts_origin="vault-shared"),
    )
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("TTS_SV_VOICE", raising=False)

    config = load_tts_config()
    plan = build_tts_plan(text="Hej från inställningar", config=config, language="sv-SE")
    payload = build_settings_explain_payload()

    assert config.sv_voice == "sv_SE-nst-medium"
    assert plan["voice_id"] == "sv_SE-nst-medium"
    assert payload["tts"]["voices"]["sv"] == {
        "value": "sv_SE-nst-medium",
        "origin": "vault-shared",
        "tier": "operator",
    }


def test_empty_settings_and_legacy_tts_env_preserve_behavior(monkeypatch) -> None:
    monkeypatch.setattr("app.tts.config.get_settings_bundle", lambda: SettingsBundle())
    monkeypatch.setenv("TTS_SV_VOICE", "legacy-voice")
    monkeypatch.setenv("TTS_ALLOW_BROWSER_FALLBACK", "1")
    monkeypatch.delenv("TTS_ALLOW_CLOUD_FALLBACK", raising=False)

    config = load_tts_config()

    assert config.sv_voice == "legacy-voice"
    assert config.allow_browser_fallback is True
    assert config.allow_cloud_fallback is False
    assert config.local_only is True


def test_no_vault_settings_explain_reports_registry_default_origin(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.cli.settings_explain.get_settings_bundle", SettingsBundle)
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.setenv("SETTINGS_RELOAD_SIGNAL_PATH", str(tmp_path / "settings-reload.json"))
    reset_settings_ingestion_state()

    payload = build_settings_explain_payload()

    assert payload["tts"]["voices"]["sv"]["origin"] == "registry default"
    reset_settings_ingestion_state()


def test_settings_explain_recovers_origin_from_compiled_generation(
    monkeypatch, tmp_path
) -> None:
    vault_root = tmp_path / "vault"
    settings_dir = vault_root / "settings"
    settings_dir.mkdir(parents=True)
    (settings_dir / "tts.md").write_text(
        "# TTS\n\n```yaml settings\nvoices:\n  sv: sv_SE-nst-medium\n```\n",
        encoding="utf-8",
    )
    runtime_dir = tmp_path / "runtime" / "settings"
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)
    monkeypatch.setattr(runtime, "RUNTIME", runtime_dir)
    monkeypatch.setattr(runtime, "_CURRENT", None)
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("SETTINGS_RELOAD_SIGNAL_PATH", str(tmp_path / "reload.json"))
    reset_settings_ingestion_state()

    compiler.compile_all(vault_root=vault_root)

    payload = build_settings_explain_payload()

    assert payload["tts"]["voices"]["sv"]["origin"] == "vault-shared"
    assert get_settings_ingestion_state().state == STATE_NO_VAULT

    (settings_dir / "global.md").write_text("# unrelated settings\n", encoding="utf-8")
    reset_settings_ingestion_state()
    unchanged_tts_payload = build_settings_explain_payload()

    assert unchanged_tts_payload["tts"]["voices"]["sv"]["origin"] == "vault-shared"
    assert get_settings_ingestion_state().state == STATE_NO_VAULT

    (settings_dir / "tts.md").unlink()
    reset_settings_ingestion_state()
    stale_payload = build_settings_explain_payload()

    assert stale_payload["tts"]["voices"]["sv"]["origin"] == "registry default"
    assert get_settings_ingestion_state().state == STATE_NO_VAULT


def test_settings_explain_keeps_retained_origin_after_invalid_replacement(
    monkeypatch, tmp_path
) -> None:
    """A fresh process keeps the published vault provenance during degradation."""
    vault_root = tmp_path / "vault"
    settings_dir = vault_root / "settings"
    settings_dir.mkdir(parents=True)
    source = settings_dir / "tts.md"
    source.write_text(
        "# TTS\n\n```yaml settings\nvoices:\n  sv: sv_SE-nst-medium\n```\n",
        encoding="utf-8",
    )
    runtime_dir = tmp_path / "runtime" / "settings"
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)
    monkeypatch.setattr(runtime, "RUNTIME", runtime_dir)
    monkeypatch.setattr(runtime, "_CURRENT", None)
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("SETTINGS_RELOAD_SIGNAL_PATH", str(tmp_path / "reload.json"))
    reset_settings_ingestion_state()

    compiler.compile_all(vault_root=vault_root)

    # The watcher has written an invalid replacement, but the last complete
    # compiled generation remains the one the fresh process can serve.
    source.write_text(
        "# TTS\n\n```yaml settings\nfallback_policy: [unterminated\n```\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "_CURRENT", None)
    reset_settings_ingestion_state()

    payload = build_settings_explain_payload()

    assert payload["tts"]["voices"]["sv"]["origin"] == "vault-shared"
    reset_settings_ingestion_state()


def test_settings_explain_uses_compiled_tts_provenance_for_compatibility_and_last_valid(
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.cli.settings_explain.get_settings_bundle", SettingsBundle)
    monkeypatch.delenv("VAULT_ROOT", raising=False)

    for state in (
        SettingsIngestionState(state="ok", source="vault", tts_origin="vault-shared"),
        SettingsIngestionState(
            state="degraded_last_valid", source="vault", tts_origin="vault-shared"
        ),
    ):
        monkeypatch.setattr(
            "app.cli.settings_explain.get_settings_ingestion_state", lambda: state
        )
        assert build_settings_explain_payload()["tts"]["voices"]["sv"]["origin"] == "vault-shared"


def test_tts_fallback_policy_stays_explicit_and_tier_gated(monkeypatch) -> None:
    bundle = SettingsBundle(tts=TTSSettings(fallback_policy="browser"))
    monkeypatch.setattr("app.tts.config.get_settings_bundle", lambda: bundle)
    monkeypatch.delenv("TTS_ALLOW_BROWSER_FALLBACK", raising=False)
    monkeypatch.delenv("TTS_ALLOW_CLOUD_FALLBACK", raising=False)
    monkeypatch.delenv("PKM_SETTINGS_PROFILE", raising=False)

    assert load_tts_config().allow_browser_fallback is False
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    assert load_tts_config().allow_browser_fallback is True
