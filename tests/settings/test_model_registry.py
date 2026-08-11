from __future__ import annotations

import pytest

from app.components.settings.models_loader import load_model_registry, load_models

pytestmark = pytest.mark.not_pg


def test_model_registry_loads() -> None:
    reg = load_model_registry()
    assert reg.version >= 1
    ids = {m.id for m in reg.models}
    assert "openai.chat.gpt_5_4_mini" in ids
    assert "openai.chat.gpt_5_4" in ids
    assert "openai.chat.gpt_4_1_mini" in ids
    assert "openai.chat.gpt_4_1" in ids
    assert "ollama.chat.llama3_1_8b" in ids
    assert "ollama.embed.nomic_embed_text" in ids
    assert "mock.chat" in ids
    assert "mock.embed" in ids


def test_models_load_and_match_manifest() -> None:
    models = load_models()
    assert models["openai.chat.gpt_5_4_mini"].provider == "openai"
    assert models["mock.embed"].kind == "embedding"
    assert models["mock.embed"].dims is not None
