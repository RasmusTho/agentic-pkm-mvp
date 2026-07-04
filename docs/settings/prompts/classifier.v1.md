---
State: SoT v5.5 baseline (prompt contract; settings-backed).
prompt_id: classifier.v1
version: 1
status: active
standards: [json_schema, mcp, a2a]
inputs_schema: app/schemas/prompts/classifier_input.v1.json
outputs_schema: app/schemas/prompts/classifier_output.v1.json
allowed_models: [ollama.chat.llama3_1_8b]
---
System:
You are the Classifier agent in a single-user PKM system. Classify the object into a stable type and tags.
Return JSON that matches outputs_schema. Be strict.

User:
Object summary:
{{summary}}

Object text:
{{text}}

Output schema version:
- This prompt (version 1) produces JSON pinned to output schema version **v1**:
  `app/schemas/prompts/classifier_output.v1.json` (the `outputs_schema` in the
  frontmatter above). Invariant I-C3: the prompt version and the output schema
  version are bound — bumping either requires bumping the prompt contract
  (a new `classifier.v2` mirror + schema pin), never silently redefining v1.
- Any model or prompt-version change to this Router prompt requires a
  baseline-vs-candidate scorecard compare artifact on the PR — see
  `docs/eval.md :: Scorecard compare`.
