---
name: jev-direct
description: Make one bounded, typed Jev judgment during local development without exposing the API key to Codex or Claude.
---

# Direct Jev Call

Use Jev for a bounded development-time choice, score, or yes/no judgment when that can help with
the current task. Jev returns typed answers; it is not a chat or code-completion model and does not
change the model that powers Codex or Claude.

The direct route is a local development tool on the current Mac. Send a small JSON object on stdin with
only `state` and `questions`; the command fixes the provider model and endpoint. For example:

    printf '%s' '{"state":{"candidate_count":2},"questions":{"best":{"type":"choice","instructions":"Which option best fits the stated goal?","criteria":{"a":"Option A","b":"Option B"}}}}' | "$HOME/.local/bin/jev-direct"

The command resolves `typesafe.api-key` internally through the existing local secret helper and
returns only validated answer JSON plus usage counts. Never inspect or print the key, call
the helper for the key yourself, put credentials in arguments/environment/files, or include raw
vault notes, credentials, private user data, or broad repository contents in `state`. Minimize the
state to the information needed for the typed question.

Each invocation sends one external request. If it times out, errors, or exits before returning a
validated result, treat the outcome as indeterminate because the request may have reached TypeSafe.
Do not retry or replay it; surface the unavailable result and continue with the normal development
workflow. Do not treat Jev output as approval for a write, deployment, Issue transition, or other
authority-bearing action. The local command does not configure Product, Builder, MARR, VM, or
production routes.

## Workflow continuation

Apply `.codex/skills/README.md :: Workflow continuation` for the governing Builder task. Use returned
typed values only as bounded development evidence; preserve the current Issue contract, code
review, tests, and any existing human confirmation gates.
