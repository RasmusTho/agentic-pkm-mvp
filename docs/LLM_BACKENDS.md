# LLM Backends

QA-agenten och klassificeringssteget kan växla backend via miljövariabler. Detta dokument beskriver skillnader, tidsouts och planerade förbättringar.

<!-- SECTION:LLM:BEGIN -->
## Stöd idag
- **Mock** – Aktiveras med `LLM_PROVIDER=mock`. Returnerar `LLM_MOCK_RESPONSE` utan nätverk (`app/agents/qa/agent.py:24-28`, `app/llm/adapter.py:12-14`). Används i tester/CI.
- **Ollama** – Default i produktion (`LLM_PROVIDER=ollama`). QA-agenten kallar `/api/chat` (`app/agents/qa/agent.py:31-48`), embeddings går mot `/api/embeddings` (`app/llm/embeddings.py:34-43`). Kräver lokal Ollama-daemon.
- **OpenAI & DeepSeek** – Exponeras via `app/llm/adapter.py:25-47`. Kräver respektive API-nycklar och används i pipeline-delar som anropar `generate(...)`.

## Konfiguration
| Scenario | Variabler | Kommentar |
| --- | --- | --- |
| Mock (standard i CLI/tests) | `LLM_PROVIDER=mock`, `LLM_MOCK_RESPONSE='{"type":"note", ...}'` | Ingen nättrafik. Health-check hoppar över Ollama-testet. |
| Lokal Ollama | `LLM_PROVIDER=ollama`, `OLLAMA_HOST=http://127.0.0.1:11434`, `OLLAMA_MODEL=llama3.1:8b-instruct`, `OLLAMA_EMBED_MODEL=nomic-embed-text:latest` | Håll modeller pre-pullade (`ollama pull llama3.1:8b`). |
| DeepSeek via Ollama-tag | `LLM_PROVIDER=ollama`, `OLLAMA_MODEL=deepseek-r1:8b` | Samma health-check gäller. Pull modellen via `ollama pull deepseek-r1:8b`. |
| OpenAI API | `LLM_PROVIDER=openai`, `OPENAI_API_KEY=...`, `LLM_MODEL=gpt-4o-mini` | `LLM_TIMEOUT` default 60 s. Ingen inbyggd retry → kör via `DEFAULT_BREAKER` vid behov. |
| DeepSeek API | `LLM_PROVIDER=deepseek`, `DEEPSEEK_API_KEY=...`, `LLM_MODEL=deepseek-chat` | Återanvänder samma `LLM_TIMEOUT`. |

## Timeouts, retries och breaker-policy
- `LLM_TIMEOUT` används i alla HTTP-anrop (QA, embeddings, adapter). Standardvärden: 120 s för chat, 60 s för embeddings/andra API:er.
- Ingen automatisk retry per anrop idag; health-check gör endast reachability-test.
- `app/quality/guardrails.DEFAULT_BREAKER` är tillgänglig för framtida integration (t.ex. att lägga runt `_call_llm`). Se docs/QUALITY.md för plan.
- För att skydda CLI körning kan du sätta `LLM_PROVIDER=mock` temporärt och endast slå på Ollama när servern är redo.

## DeepSeek via Ollama-tag
- Lägg modellen lokalt: `ollama pull deepseek-r1:8b`.
- Sätt `OLLAMA_MODEL=deepseek-r1:8b` och `LLM_MAX_TOKENS` enligt behov (DeepSeek tenderar att vara verbosare → använd `max_tokens` < 400).
- Begränsningar: reasoning-svar (tänk "chain-of-thought") kommer fortfarande i klarspråk. Maskning måste göras innan loggning (`docs/PRIVACY.md`).
<!-- SECTION:LLM:END -->
