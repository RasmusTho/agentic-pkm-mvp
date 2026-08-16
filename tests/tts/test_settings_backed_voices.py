from __future__ import annotations

from app.cli.settings_explain import build_settings_explain_payload
from app.settings import compiler
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


def test_tts_fallback_policy_stays_explicit_and_tier_gated(monkeypatch) -> None:
    bundle = SettingsBundle(tts=TTSSettings(fallback_policy="browser"))
    monkeypatch.setattr("app.tts.config.get_settings_bundle", lambda: bundle)
    monkeypatch.delenv("TTS_ALLOW_BROWSER_FALLBACK", raising=False)
    monkeypatch.delenv("TTS_ALLOW_CLOUD_FALLBACK", raising=False)
    monkeypatch.delenv("PKM_SETTINGS_PROFILE", raising=False)

    assert load_tts_config().allow_browser_fallback is False
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    assert load_tts_config().allow_browser_fallback is True
