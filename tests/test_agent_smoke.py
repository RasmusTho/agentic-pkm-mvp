from __future__ import annotations

from types import SimpleNamespace

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


def test_qa_agent_uses_shared_model_access_router(monkeypatch):
    intents = []
    chat_calls = []

    class _Client:
        def chat(self, name, pack, **kwargs):
            chat_calls.append((name, pack, kwargs))
            return "Alpha is confirmed by the source and is the main point of the note. " * 2 + "[#1]"

    monkeypatch.setattr(
        qa_agent,
        "_QA_SETTINGS",
        SimpleNamespace(
            enable=True,
            search_k=1,
            context_docs=1,
            llm=SimpleNamespace(max_tokens=64),
        ),
    )
    monkeypatch.setattr(
        qa_agent,
        "hybrid_search",
        lambda *_args, **_kwargs: [
            {"doc_id": "doc-1", "source_ref": "alpha.md", "snippet": "Alpha fact", "score": 0.9}
        ],
    )

    def _get_chat_client(intent):
        intents.append(intent)
        return _Client()

    monkeypatch.setattr(qa_agent, "get_chat_client", _get_chat_client)
    result = qa_agent.answer("What does the source confirm?", trace_id="T-QA-ROUTER")

    assert result["sources"] == [{"doc_id": "doc-1", "source_ref": "alpha.md"}]
    assert len(intents) == 1 and intents[0].task_kind == "qa"
    assert len(chat_calls) == 1 and chat_calls[0][0] == "qa"
