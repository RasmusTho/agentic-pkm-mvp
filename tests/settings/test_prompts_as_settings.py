from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.ask import utils as ask_utils
from app.api.app import app
from app.settings import compiler, runtime
from app.settings.models import DEFAULT_ASK_SYSTEM_PROMPT
from app.vault.manager import VaultManager


def _configure_vault(monkeypatch, tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    VaultManager().initialize_vault(vault, remember=False)
    monkeypatch.setattr(compiler, "RUNTIME", tmp_path / "runtime" / "settings")
    monkeypatch.setattr(runtime, "RUNTIME", compiler.RUNTIME)
    runtime._CURRENT = None
    return vault


def test_ask_prompt_resolves_from_vault(monkeypatch, tmp_path: Path) -> None:
    vault = _configure_vault(monkeypatch, tmp_path)
    prompt = "Use the vault prompt exactly."
    (vault / "settings" / "prompts" / "ask.md").write_text(prompt, encoding="utf-8")

    compiler.compile_all(vault_root=vault, auto_heal=False)

    captured: dict[str, str] = {}

    class Run:
        status = "ok"
        result = {"answer": "ok"}
        llm_route = None

    def fake_run(*args, **kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        return Run()

    monkeypatch.setattr(ask_utils, "run_reasoning", fake_run)
    ask_utils.llm_answer("question", "context", ask_utils.get_ask_settings())
    assert captured["system_prompt"] == prompt

    without_prompt = tmp_path / "without-prompt"
    (without_prompt / "settings").mkdir(parents=True)
    compiler.compile_all(vault_root=without_prompt, auto_heal=False)
    runtime._CURRENT = None
    monkeypatch.setenv("VAULT_ROOT", str(without_prompt))
    assert ask_utils.get_ask_settings().system_prompt == DEFAULT_ASK_SYSTEM_PROMPT


def test_validate_reads_canonical_prompts(monkeypatch, tmp_path: Path) -> None:
    vault = _configure_vault(monkeypatch, tmp_path)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    (vault / "settings" / "prompts" / "ask.md").write_text("", encoding="utf-8")

    response = TestClient(app).get("/api/settings/validate")

    assert response.status_code == 200
    assert any(issue["code"] == "prompts.invalid" for issue in response.json()["issues"])


def test_loader_removed_once_unused() -> None:
    assert not Path("app/components/settings/prompts_loader.py").exists()
    assert not list(Path("app").rglob("*prompts_loader*"))
