from __future__ import annotations

from app.agents.qa import agent as qa_agent
from app.retrieval.hybrid import get_store


def test_qa_agent_answer(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    store = get_store()
    store.set_documents(
        [
            {"doc_id": "doc-1", "text": "Alpha dokument innehåller fakta.", "source_ref": "alpha.md"},
            {"doc_id": "doc-2", "text": "Beta dokument är orelaterat."},
        ]
    )

    def fake_call(messages, trace_id, max_tokens):
        return "Sammanfattning av alpha [#1]"

    monkeypatch.setattr(qa_agent, "_call_llm", fake_call)

    result = qa_agent.answer("Vad säger alpha dokumentet?", trace_id="T-QA")

    assert result["sources"]
    assert "[#1]" in result["answer"]
