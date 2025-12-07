State: SoT v4.10 Reality-MVP (current core).
# Quality & Guardrails

The agent loop prioritizes deterministic policies over heuristic “best effort”.

<!-- SECTION:QUALITY:BEGIN -->
## Guardrails (app/quality/guardrails.py:11-69)
- **Forbidden content** – `_FORBIDDEN_RE` blocks strings matching `api key|password|secret` (case-insensitive). Sanitize responses before returning.
- **Token budget** – `enforce_quality` default `max_tokens=800`. Exceeding it emits `too_long`.
- **Source requirement** – `min_sources=1`. Empty `sources` → `insufficient_sources`.
- **Circuit breaker** – `CircuitBreaker` + `DEFAULT_BREAKER` track failed calls (3 failures within 60 s). Not wired into QA yet.

## Agent loop controls
| Step | Location | Check | Failure pattern |
| --- | --- | --- | --- |
| `draft_answer` | app/agents/qa/agent.py:59-79 | Prompt enforces `[#{i}]` citations. | Missing context → self-check flags issues. |
| `self_check` | app/agents/qa/agent.py:82-107 | Verifies references + word count ≥ 30. | `missing_references`, `too_short`. |
| `finalize` | app/agents/qa/agent.py:109-115 | Appends a notice when evidence is weak. | `_Note: limited evidence._` appended. |
| `enforce_quality` | app/quality/guardrails.py:14-29 | Final filter before returning. | `issues` array feeds the client/log. |

## Performance budgets (tracked via spans)
- **ASR / transcribe** (`transcribe`) – target < 30 s for a 5-minute clip (`jq 'select(.node=="transcribe")'`).
- **Retrieval** (`agent.answer` early stage) – p95 < 250 ms (link CLI `trace_id`).
- **QA answer** (`agent.answer`) – p95 < 1.2 s with Ollama 8B locally. If `status=error`, consider opening the breaker.

## Planned improvements
1. Wrap `_call_llm` with `DEFAULT_BREAKER` and log `extra={"breaker": "open"}` when tripped.
2. Apply `timeout_wrapper` to transcribe/ASR to stop hanging ffmpeg processes.
3. Add cross-encoder rerank per `docs/ROADMAP.md` to improve precision before prompting the agent.
<!-- SECTION:QUALITY:END -->
