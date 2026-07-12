---
name: start-model-inquiry
description: "Launch a durable pre-ticket Fable and GPT architecture inquiry through the shared BuilderOps command when a development question needs independent model review before ticket creation."
---

# Start Model Inquiry

Use this Builder System skill when the operator asks to investigate a concrete development question
before issue creation. It starts and runs the durable artifact-first workflow; it does not conduct
the inquiry in chat history.

## Launch

1. Confirm the current workspace is the canonical `agentic-pkm-mvp` checkout or one of its Git
   worktrees.
2. Write the question verbatim to a mode-`0600` temporary UTF-8 file. Do not interpolate it into a
   shell command.
3. Run:

   ```bash
   scripts/start_model_inquiry.sh --question-file "$QUESTION_FILE"
   ```

4. Delete the temporary input file.
5. Report the returned `inquiry_id`, `final_state`, `terminal_receipt_id`, and
   `human_readable_report`. The last value is the Markdown file a human should open; the adjacent
   JSON files remain the canonical audit trace.

The launcher validates the shared vault and both explicit role adapters before it writes an
inquiry. If preflight fails, surface the error and stop. Never substitute an in-chat Fable/GPT
exchange or silently use one model for both roles.

## Boundaries

- Do not create a GitHub Issue; use the separate promotion path after a ready receipt exists.
- Do not automate another desktop app or copy turns between apps.
- Do not write inquiry artifacts to Companion UI or a human knowledge vault.
- Do not print adapter configuration or credentials while diagnosing preflight.

The shell entrypoint uses the same canonical/worktree virtualenv resolver as `builderops_cli.sh`.
The common launcher invokes `scripts/builderops_cli.sh builderops inquiry start` and then the shared
`inquiry run` command. It returns only after the runner records a terminal outcome.
