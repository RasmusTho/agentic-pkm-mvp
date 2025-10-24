from __future__ import annotations
import os, json, requests

def _prov() -> str: return os.getenv("LLM_PROVIDER","ollama").lower()
def _model() -> str: return os.getenv("LLM_MODEL","llama3.1:8b")
def _rmodel() -> str: return os.getenv("LLM_REASONING_MODEL", _model())

def generate(messages: list[dict], *, reasoning: bool=False) -> str:
    p = _prov()
    m = _rmodel() if reasoning else _model()

    if p == "mock":
        mock = os.getenv("LLM_MOCK_RESPONSE", "UNSURE")
        return str(mock)

    if p == "ollama":
        r = requests.post(
            os.getenv("OLLAMA_HOST","http://127.0.0.1:11434") + "/api/chat",
            json={"model": m, "messages": messages, "stream": False},
            timeout=float(os.getenv("LLM_TIMEOUT","120")),
        )
        r.raise_for_status()
        return r.json()["message"]["content"]

    if p == "openai":
        api = os.environ["OPENAI_API_KEY"]
        url = os.getenv("OPENAI_BASE","https://api.openai.com/v1/chat/completions")
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {api}", "Content-Type":"application/json"},
            data=json.dumps({"model": m, "messages": messages}),
            timeout=float(os.getenv("LLM_TIMEOUT","60")),
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    if p == "deepseek":
        api = os.environ["DEEPSEEK_API_KEY"]
        url = os.getenv("DEEPSEEK_BASE","https://api.deepseek.com/chat/completions")
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {api}", "Content-Type":"application/json"},
            data=json.dumps({"model": m, "messages": messages}),
            timeout=float(os.getenv("LLM_TIMEOUT","60")),
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    raise ValueError("unsupported provider")
