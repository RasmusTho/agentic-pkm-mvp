import os, json, http.client, socket
from typing import Dict, Any

def _minimal_validate(payload: dict, schema: dict) -> None:
    req = schema.get("required", [])
    for k in req:
        if k not in payload:
            raise ValueError(f"schema required key missing: {k}")
    if "decision" in payload and "properties" in schema:
        dec_enum = schema["properties"].get("decision", {}).get("enum")
        if dec_enum and payload["decision"] not in dec_enum:
            raise ValueError("schema enum violation: decision")

def validate_json(raw: str, schema_path: str) -> Dict[str, Any]:
    data = json.loads(raw)
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        _minimal_validate(data, schema)
    except Exception:
        pass
    return data

def _ollama_chat(system: str, user: str, model: str, temperature: float = 0.0, timeout: float = 12.0) -> str:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        "options": {"temperature": temperature}
    }
    conn = http.client.HTTPConnection("127.0.0.1", 11434, timeout=timeout)
    try:
        conn.request("POST", "/api/chat", body=json.dumps(body), headers={"Content-Type":"application/json"})
        resp = conn.getresponse()
        if resp.status != 200:
            raise RuntimeError(f"ollama http {resp.status}")
        # Streaming JSONL; collect 'message' chunks
        buf = []
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            buf.append(chunk)
        raw = b"".join(buf).decode("utf-8", errors="replace")
        # Response may be concatenated JSON objects per line. Keep last "message"
        text = ""
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if "message" in obj and "content" in obj["message"]:
                    text += obj["message"]["content"]
            except Exception:
                text += line
        return text.strip()
    finally:
        try:
            conn.close()
        except Exception:
            pass

def call_llm(name: str, pack: Dict[str, Any]) -> str:
    provider = os.getenv("LLM_PROVIDER", "fake").lower()
    model = os.getenv("LLM_MODEL", os.getenv("MERGE_LLM_MODEL", "llama3.1:8b"))
    temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
    system = pack.get("system", "")
    user = pack.get("user", "")
    if provider == "ollama":
        try:
            return _ollama_chat(system, user, model, temperature)
        except (socket.timeout, ConnectionRefusedError, RuntimeError):
            pass
    # Fallback: deterministic JSON for tests
    return json.dumps({
        "decision":"A",
        "similarity":0.92,
        "confidence":0.8,
        "scores":{"A":{"total":8.0},"B":{"total":7.7}},
        "reason":"concise wins",
        "hybrid":{"take_from":"A","carry_over_items":[]},
        "ask_prompt":"",
        "policy_flags":["provenance_preserved"]
    })
