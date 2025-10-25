# LLM Configuration

## Local
Ollama models:
- llama3.1:8b for general generation
- deepseek-r1:8b for reasoning-style outputs

Setup:
brew install ollama
ollama serve &
ollama pull llama3.1:8b
ollama pull deepseek-r1:8b
export LLM_PROVIDER=ollama
export LLM_MODEL=llama3.1:8b
export LLM_REASONING_MODEL=deepseek-r1:8b

## Online fallback
Provider via env:
export LLM_PROVIDER=openai|anthropic|azure
export LLM_MODEL="model-id"
export LLM_REASONING_MODEL="model-id"
API keys are read from standard provider env vars.

## Adapter contract
generate(messages: list[{"role": "...", "content": "..."}], reasoning=False) -> str
When reasoning=True the adapter routes to LLM_REASONING_MODEL.

## Guidelines
- Deterministic tests avoid LLM calls
- Agents may use LLMs only in Plan/Reflect steps
- Always log model and parameters in audit details
