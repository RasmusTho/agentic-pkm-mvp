State: SoT v4.10 (current; details may lag ARCHITECTURE).
# LLM Integration

## Provider abstraction
Alla anrop går via `app.llm.adapter.generate(messages, reasoning=False)`. Konfiguration via miljövariabler:

| Var | Betydelse | Exempel |
|---|---|---|
| LLM_PROVIDER | ollama, openai, azureopenai, anthropic | ollama |
| LLM_MODEL | standard chattmodell | llama3.1:8b |
| LLM_REASONING_MODEL | resonemangsmodell | deepseek-r1:8b |

`reasoning=True` väljer `LLM_REASONING_MODEL`.

## Ollama (lokalt)
Adress `http://127.0.0.1:11434`. Ladda modeller med `ollama pull`. Kör en modell åt gången för att spara RAM.

## Fjärr
Sätt `LLM_PROVIDER=openai` och `OPENAI_API_KEY`. Timeout 120 s.

## Prompting
Agenter använder korta, uppgiftsbundna prompts. Resonemang loggas endast som utfall.

## Loggning
Vid `LOG_LEVEL=DEBUG` loggas `{provider, model, tokens_in, tokens_out, duration}` till audit.
