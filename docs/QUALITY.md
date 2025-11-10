# Quality & Guardrails

Agentloopen bygger på deterministiska reglers, inte heuristisk "best effort".

<!-- SECTION:QUALITY:BEGIN -->
## Guardrails (app/quality/guardrails.py:11-69)
- **Förbjudet innehåll** – `_FORBIDDEN_RE` blockerar strängar som matchar `api key|password|secret` (case-insensitive). Åtgärd: sanitera svaret innan return.
- **Tokenbudget** – `max_tokens` default 800 ord i `enforce_quality`. Överskridande flaggas som `too_long`.
- **Källkrav** – `min_sources=1`. Om `sources`-listan är tom → `insufficient_sources`.
- **Circuit breaker** – `CircuitBreaker` + `DEFAULT_BREAKER` håller koll på misslyckade anrop (3 fel / 60 s). Inte ansluten till QA ännu, men redo för LLM/backends.

## Agentloopens kontroller
| Steg | Fil | Kontroll | Felmönster |
| --- | --- | --- | --- |
| `draft_answer` | app/agents/qa/agent.py:59-79 | Prompt instruerar att citera `[#{i}]`. | Brist på kontext → self-check triggar. |
| `self_check` | app/agents/qa/agent.py:82-107 | Kollar referenser + ordantal ≥ 30. | Issues `missing_references`, `too_short`. |
| `finalize` | app/agents/qa/agent.py:109-115 | Lägg till notis vid låg evidens. | `_Notis: begränsad evidens._` biläggs. |
| `enforce_quality` | app/quality/guardrails.py:14-29 | Sista filter innan svar returneras. | `issues` lista skickas tillbaka till klient/logg. |

## Prestandabudget (övervakas via spans)
- **ASR/transcribe** (`transcribe`) – mål < 30 s för 5 min klipp. Mät via `jq 'select(.node=="transcribe")'`.
- **Retrieval** (`agent.answer` inledningen) – p95 < 250 ms. Länka `trace_id` från CLI.
- **QA-svar** (`agent.answer`) – p95 < 1.2 s när Ollama 8B körs lokalt. Om `status=error` → aktivera circuit breaker.

## Planerade förbättringar
1. Koppla `DEFAULT_BREAKER` runt `_call_llm` och logga `extra={"breaker": "open"}` vid blockering.
2. Införa `timeout_wrapper` i transcribe/ASR för att stoppa hängande ffmpeg.
3. Rerank (cross-encoder) enligt docs/ROADMAP.md för bättre precision innan agentprompten.
<!-- SECTION:QUALITY:END -->
