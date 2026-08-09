from app.llm.embeddings import PROVIDER_REGISTRY
from app.settings import Settings


def test_settings_declares_no_unservable_embed_model() -> None:
    """The settings default must name a model served by the shipped Ollama adapter."""

    assert Settings.model_fields["embed_model"].default == "nomic-embed-text:latest"
    assert "ollama" in PROVIDER_REGISTRY
