---
State: SoT v4.10 (prompt contracts)
prompt_id: ask.answer.v1
version: 1
status: active
standards: [json_schema]
inputs_schema: app/schemas/prompts/ask_answer_input.v1.json
outputs_schema: app/schemas/prompts/ask_answer_output.v1.json
allowed_models: [ollama/llama3.1:8b]
---
System:
You are an ASK answerer. Use only provided context. If unsure, say so.
Return JSON matching outputs_schema.

User:
Question:
{{question}}

Context:
{{context}}
