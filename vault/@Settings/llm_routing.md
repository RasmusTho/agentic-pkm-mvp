---
uuid: 00000000-0000-0000-0000-000000000006
title: LLM Routing
origin: user
review_state: evergreen
trust: internal
---
## Task routing defaults
```yaml settings
default_chat:
  primary:
    provider: openai
    model: gpt-4.1-mini
  fallback:
    mode: local
    provider: ollama
    model: llama3.1:8b

default_reasoning:
  primary:
    provider: openai
    model: gpt-4.1
  fallback:
    mode: local
    provider: ollama
    model: llama3.1:8b

default_embedding:
  primary:
    provider: ollama
    model: nomic-embed-text:latest
    profile: default
  fallback:
    mode: never
  require_compatible_identity: true

tasks:
  qa:
    primary:
      provider: openai
      model: gpt-4.1-mini
    fallback:
      mode: local
      provider: ollama
      model: llama3.1:8b
  classify:
    primary:
      provider: openai
      model: gpt-4.1-mini
    fallback:
      mode: local
      provider: ollama
      model: llama3.1:8b
  plan:
    primary:
      provider: openai
      model: gpt-4.1
    fallback:
      mode: local
      provider: ollama
      model: llama3.1:8b
  embed:
    primary:
      provider: ollama
      model: nomic-embed-text:latest
      profile: default
    fallback:
      mode: never
    require_compatible_identity: true
```

## Notes
- Chat/reasoning tasks may choose a local fallback.
- Embeddings must keep a compatible identity. Endpoint repair is allowed; incompatible model fallback is not.
