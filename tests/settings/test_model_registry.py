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
    assert "openai.chat.gpt_6_astra" in ids


def test_models_load_and_match_manifest() -> None:
    models = load_models()
    assert models["openai.chat.gpt_5_4_mini"].provider == "openai"
    assert models["mock.embed"].kind == "embedding"
    assert models["mock.embed"].dims is not None


def test_registry_includes_gpt_6_astra() -> None:
    astra = load_models()["openai.chat.gpt_6_astra"]

    assert astra.status == "active"
    assert astra.kind == "chat"
    assert astra.provider == "openai"
    assert astra.model == "gpt-6-astra"


def test_gpt_6_astra_pricing_provenance() -> None:
    pricing = load_models()["openai.chat.gpt_6_astra"].pricing

    assert pricing is not None
    assert pricing.standard_input_usd_per_million_tokens == 10.0
    assert pricing.standard_output_usd_per_million_tokens == 50.0
    assert pricing.fast_mode_multiplier == 2.0
    assert pricing.retrieved_on.isoformat() == "2026-09-06"
    assert pricing.source_urls == [
        "https://openai.com/index/gpt-6-astra/",
        "https://artificialanalysis.ai/models/releases/gpt-6-astra",
    ]
    assert pricing.artificial_analysis_cost_per_intelligence_index_task_usd == {
        "low": 0.63,
        "medium": 1.16,
        "high": 1.41,
        "non_reasoning": 1.42,
        "xhigh": 1.85,
        "max": 2.57,
    }


def test_gpt56_registry_has_unique_complete_descriptors() -> None:
    from datetime import date

    models = load_models()
    for tier, rates in {"luna": (0.2, 0.02, 1.2), "terra": (2, 0.2, 12), "sol": (4, 0.4, 20)}.items():
        matches = [m for m in models.values() if m.model == f"gpt-5.6-{tier}"]
        assert len(matches) == 1
        model = matches[0]
        assert (model.provider, model.kind, model.status) == ("openai", "chat", "active")
        assert "openai_api" in model.allowed_transports + model.explicit_eval_transports
        pricing = model.pricing
        assert pricing is not None
        assert (pricing.standard_input_usd_per_million_tokens,
                pricing.standard_cached_input_usd_per_million_tokens,
                pricing.standard_output_usd_per_million_tokens) == rates
        assert pricing.retrieved_on == date(2026, 9, 28)
        assert pricing.source_urls == [f"https://developers.openai.com/api/docs/models/gpt-5.6-{tier}"]
    assert models["openai.chat.gpt_5_6_luna"].selection_group == "luna"
