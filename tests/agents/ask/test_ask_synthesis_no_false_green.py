from __future__ import annotations

from app.agents.ask.graph import _answer_node
from app.agents.ask.state import AgentState, RetrievedHit
from app.agents.ask.utils import get_ask_settings
from app.services import llm as llm_service


def test_provider_failure_yields_snippet_without_receipt(monkeypatch, clean_llm_env, tmp_path) -> None:
    """Gate admits, but the real-provider generation fails → ASK emits NO
    synthesis_receipt_id and serves the literal snippet.

    This asserts the guard in ``app/agents/ask/graph.py::_answer_node``: when
    ``llm_answer`` returns ``None`` (because ``call_llm`` now propagates the
    provider error instead of returning a canned stub, #2108), the node must
    fall back to the literal snippet and emit no activation receipt. A canned
    answer or a receipt here is a false green (#1997 / #1999 / gate #2026).
    """
    receipts = tmp_path / "ask_synthesis_receipts.jsonl"
    clean_llm_env.setenv("ASK_SYNTHESIS_RECEIPTS_PATH", str(receipts))
    clean_llm_env.setenv("LLM_PROVIDER", "ollama")
    clean_llm_env.setenv("LLM_PROVIDER_ENFORCE", "1")
    clean_llm_env.setenv("LLM_MODEL", "llama3.1:8b")
    clean_llm_env.setenv("OLLAMA_URL", "http://127.0.0.1:11434")
    clean_llm_env.setenv("REASONING_PROVIDER", "llm")
    clean_llm_env.delenv("CI", raising=False)
    clean_llm_env.delenv("LLM_MOCK_RESPONSE", raising=False)
    monkeypatch.setattr(llm_service, "_DEFAULT_BASE_DELAY", 0.0)
    monkeypatch.setattr(llm_service, "_DEFAULT_MAX_RETRIES", 1)

    def _boom(*args, **kwargs):
        raise RuntimeError("ollama http 404: model not served")

    monkeypatch.setattr(llm_service, "_ollama_chat", _boom)

    snippet = "The capital of France is Paris."
    state = AgentState(
        trace_id="T-failloud",
        query="What is the capital of France?",
        hits=[
            RetrievedHit(
                object_id="11111111-1111-1111-1111-111111111111",
                score=0.9,
                snippet=snippet,
                text=snippet,
                title="France",
                path="france.md",
                payload={"text": snippet, "origin": "vault"},
            )
        ],
    )

    result = _answer_node(state, ask_settings=get_ask_settings())

    # No synthesis happened → no receipt id, literal snippet served.
    assert result.synthesis_receipt_id is None
    assert result.answer == snippet
    # And no activatable receipt line was written for a non-synthesis.
    if receipts.exists():
        assert all(
            '"outcome":"activatable"' not in line
            for line in receipts.read_text(encoding="utf-8").splitlines()
        )
