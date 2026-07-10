---
name: start-model-inquiry
description: Launch a durable pre-ticket Fable and GPT architecture inquiry from an accessible agentic-pkm-mvp checkout when a development question needs independent model review before ticket creation.
---

# Start Model Inquiry

Use this skill only when the operator asks to investigate a development question through the
BuilderOps model-inquiry workflow before creating a ticket.

## Launch

1. Require an accessible `agentic-pkm-mvp` checkout. Resolve its root from the current workspace or
   the operator-provided `AGENTIC_PKM_REPO_ROOT`, and set that resolved path as `REPO_ROOT`; never
   guess a private application path.
2. Write the question verbatim to a mode-`0600` temporary UTF-8 file. Do not interpolate it into a
   shell command.
3. Run exactly:

   ```bash
   "$REPO_ROOT/scripts/start_model_inquiry.sh" --question-file "$QUESTION_FILE"
   ```

4. Delete the temporary input file.
5. Return the JSON `inquiry_id`, `final_state`, and `terminal_receipt_id` to the operator.

The launcher performs vault and adapter preflight before writing the inquiry. Propagate any error
verbatim enough to identify the missing dependency; do not fall back to chat-only orchestration.

## Boundaries

- Do not copy turns between desktop apps.
- Do not automate clicks, keystrokes, windows, tabs, or another desktop app.
- Do not create a GitHub Issue; promotion is a separate governed step.
- Do not write model transcripts to Companion UI or a human knowledge vault.

If the Claude execution environment cannot access the checkout or its configured shared vault,
stop and report that boundary. The portable package does not claim to provide a host-filesystem
bridge.
