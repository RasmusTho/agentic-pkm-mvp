State: Advisory audit snapshot (2026-07-09) of Yggdrasil Builder System skill/workflow posture against five YouTube transcripts and current external agentic-coding sources.
Doc role: Reference (audit snapshot)
Authority: Evidence-based Builder System workflow analysis only. Proposes no Product/Runtime System authority changes and creates no executable backlog without owner promotion.

# Builder System Skill Review - 2026-07-09

## Scope

This audit reviews the Builder System skill set and workflow posture, with emphasis on:

- requirement elicitation / "grilling"
- planning and large-work decomposition
- code review and verification loops
- transcript-acquisition pipeline behavior observed while using the system's YouTube path

It is subordinate to `docs/DOCS_INDEX.md`, `AGENTS.md`, `.codex/skills/README.md`, `docs/architecture/SBS_OPERATING_MODEL.md`, and owner rulings.

## Evidence Pack

### Local YouTube Transcript Corpus

Transcripts and manifest were saved under:

- `docs/research/builder-system-skill-review-2026-07-09/youtube_manifest.json`
- `docs/research/builder-system-skill-review-2026-07-09/transcripts/A8mokin_YOs.normalized.md`
- `docs/research/builder-system-skill-review-2026-07-09/transcripts/kwSVtQ7dziU.normalized.md`
- `docs/research/builder-system-skill-review-2026-07-09/transcripts/ib74sLgjIBM.normalized.md`
- `docs/research/builder-system-skill-review-2026-07-09/transcripts/suY66oTDn0s.normalized.md`
- `docs/research/builder-system-skill-review-2026-07-09/transcripts/gsvZn4nbFus.normalized.md`

The sixth submitted URL duplicated `A8mokin_YOs`; the manifest records both input URLs on the same video entry.

Raw VTT/JSON files were generated during local acquisition but are intentionally not retained in this repo artifact because they duplicate the normalized corpus and manifest metadata.

Transcript acquisition used the repository YouTube pipeline components (`yt_dlp_extract_info`, caption fetch, transcript normalization). Two videos exposed a caption-selector defect: their metadata language was `en-US`, while usable automatic caption keys were `en-orig` / `en`. The current selector treated them as captionless and entered slow ASR fallback. The saved transcripts use an explicit original-English caption workaround, recorded in the manifest.

### External Sources

Recent and authoritative sources consulted:

- OpenAI Codex best practices: https://developers.openai.com/codex/learn/best-practices
- Anthropic Claude Code best practices: https://code.claude.com/docs/en/best-practices
- Anthropic Claude Code subagents: https://code.claude.com/docs/en/sub-agents
- Anthropic Claude Code auto mode: https://www.anthropic.com/engineering/claude-code-auto-mode
- GitHub Copilot best practices: https://docs.github.com/en/copilot/get-started/best-practices
- GitHub Copilot code review: https://docs.github.com/en/copilot/concepts/agents/code-review
- GitHub Copilot coding-agent validation tools changelog: https://github.blog/changelog/2026-03-18-configure-copilot-coding-agents-validation-tools/
- GitHub Copilot cloud-agent planning changelog: https://github.blog/changelog/2026-04-01-research-plan-and-code-with-copilot-cloud-agent/
- c-CRAB code-review-agent benchmark: https://arxiv.org/abs/2603.23448
- ProjDevBench end-to-end project-development benchmark: https://arxiv.org/abs/2602.01655
- SWE-EVO long-horizon software-evolution benchmark: https://arxiv.org/html/2512.18470v5

## Current Builder System Posture

The existing Builder System is strongest after intent has become an executable issue. The documented chain in `.codex/skills/README.md` already has a clear path from docs/spec to issue, project state, implementation, PR, CI, verification, closure, and owner-doc writeback. `feature-breakdown` also has the right instinct: stop at doc enrichment when docs are too vague, keep acceptance criteria verifiable, and preserve cross-task invariants.

The main weakness is earlier in the funnel. `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md` already marks intent capture, model routing, skill routing, context building, human exception routing, review gate running, evidence-pack building, and closure automation as partial or implicit. The transcript corpus and external sources point to the same gap: agentic development quality depends less on raw coding and more on disciplined problem definition, context control, decomposition, independent review, and durable learning from repeated failures.

## Findings

### F1 - Requirement grilling is not first-class enough

The current system can refuse vague work through `feature-breakdown` and `issue-to-code`, but it does not appear to have a dedicated Builder skill for eliciting requirements before specs/issues exist.

The Matt Pocock transcript is especially relevant: grilling improved when questions were asked one at a time, when the agent separated facts it could discover from decisions only the human could make, and when a confirmation gate preceded plan execution. This maps directly onto Yggdrasil's owner-decision and authority-separation doctrine.

Recommended posture: create a first-class `requirement-grilling` skill before `feature-breakdown`.

Expected output:

- problem statement
- facts discovered from repo/docs/search
- human-only decisions
- assumptions and risk register
- open questions, asked sequentially
- out-of-scope boundaries
- acceptance hypotheses with tentative `Verify:` routes
- explicit confirmation receipt before spec/ticket creation

### F2 - Large-work planning needs a Wayfinder layer

For small bounded issues, the existing `docs-to-issue -> issue-to-code -> verification-and-closure` path is appropriate. For ambiguous or multi-session work, the system needs a map before a spec: decisions, research tasks, prototypes, executable tasks, blocking relationships, and promotion points.

The YouTube corpus converges on this pattern: plan first, create research/prototype work before committing to implementation shape, and use stronger planning/review roles to supervise cheaper or narrower execution roles. OpenAI, Anthropic, and GitHub sources also emphasize plan-first behavior for ambiguous work and review/approval before code.

Recommended posture: add a `wayfinder` or `builder-wayfinder` skill that creates a decision map, not a product spec.

Expected output:

- decision graph
- research tickets
- prototype tickets
- executable implementation tickets
- blocker relationships
- risk/TCD classification
- context-pack requirements
- promotion boundary: "what evidence allows this to become feature-breakdown/docs-to-issue input?"

### F3 - Planning lacks an explicit adversarial review gate

The Builder System already has review after implementation, but high-risk plans should be challenged before code begins. This is especially important for changes touching authority boundaries, persistence, settings, governance, or multi-repo client contracts.

Recommended posture: add a `plan-review` step for high-risk, multi-file, or ambiguous work.

The reviewer should check:

- whether the plan is solving the stated problem
- whether owner docs and authority boundaries are correctly identified
- whether acceptance criteria have concrete verification routes
- whether failure modes and partial states are covered
- whether the work should be split into research/prototype/spec/ticket phases
- whether any human decision is still missing

This should produce a short plan-review receipt before `issue-to-code` claims execution.

### F4 - Code review is present but should be more explicit, axis-based, and durable

`verification-and-closure` already requires a local review gate and an independent fresh reviewer. That is directionally strong. The gap is that the review taxonomy and durable record are not yet first-class repo-governed artifacts.

Recommended review axes:

- requirements / acceptance-criteria satisfaction
- repository standards and owner-doc conformance
- code smells and maintainability
- security/data/authority/migration risk where relevant
- semantic diff / contract-delta review for schemas, events, invariants, settings, and client contracts

Anthropic's review guidance is a useful constraint: blocking findings should affect correctness, stated requirements, or material safety/security/maintainability, not generic overengineering preferences.

GitHub's coding-agent validation direction and the c-CRAB benchmark both support moving review from chat-local judgment toward repeatable checks, externalized receipts, and benchmark-like evaluation of review quality.

### F5 - Context-pack and model/role routing remain implicit

The Builder System documents already identify model router, skill router, and context builder as gaps. External sources converge on the same failure mode: broad context and long sessions degrade outcomes, while explicit context packs and specialized subagents improve quality and cost control.

Recommended posture:

- require source-anchor context packs for large or high-risk work
- route exploration to read-only subagents where useful
- clear/fork execution context after heavy grilling/research when practical
- record why a task used "planner/reviewer/executor" roles
- make repeated correction patterns candidates for skill updates

### F6 - YouTube pipeline needs a small correctness hardening pass

Pipeline findings from this run:

- caption fetch works, but `youtube_plugin.fetch` fails loudly after caption retrieval unless `STORE_BACKEND=memory` or a durable backend is configured
- BCP-47 language variants such as `en-US` are not matched to `en-orig` / `en` automatic caption keys before ASR fallback
- ASR fallback can block a batch for minutes and should have clearer progress, timeout, and partial-output behavior

Recommended backlog:

- add caption-selector fallback: `en-US` -> `en-orig` / `en` before ASR
- add a transcript-export command/mode that persists caption artifacts without requiring a durable store
- add batch resilience: per-video timeout, partial manifest writes, and clear "ASR pending/failed" status
- add a lightweight pipeline fixture covering `en-US` metadata with `en-orig` captions

## Recommended Skill Changes

### 1. Add `.codex/skills/requirement-grilling/`

Purpose: turn ambiguous human intent into a confirmed requirement map before specs/issues/code.

Hard rules:

- ask one human question at a time
- separate discovered facts from human decisions
- do not ask the model to answer its own product decisions
- stop before spec/ticket/code unless shared understanding is confirmed
- preserve unresolved decisions as human-exception packets or owner-decision items

### 2. Add `.codex/skills/wayfinder/`

Purpose: create a decision/research/prototype/task map for large work before feature breakdown.

This should sit between raw intent and `feature-breakdown`. It should be explicitly non-authoritative until owner-promoted.

### 3. Add or formalize `.codex/skills/plan-review/`

Purpose: adversarially review high-risk plans before execution.

This can be a standalone skill or a mandatory phase inside `feature-breakdown` for Tier 2+ / high-risk work.

### 4. Add `.codex/skills/code-review/` or repo-governed review instructions

Purpose: make the current local `/code-review` expectation durable and inspectable.

It should define review axes, blocking/non-blocking classification, semantic-diff checks, and receipt format.

### 5. Update `.codex/skills/README.md`

If the above are accepted, the canonical chain should become:

```text
Intent -> requirement-grilling / wayfinder -> feature-breakdown -> docs-to-issue -> issue-to-code -> publish PR -> CI -> code review -> verification-and-closure -> owner-doc writeback
```

Small bounded fixes may still bypass grilling when the issue is already Ready, scoped, and verifiable.

## Proposed Invariants

- `REQ-1 facts-decisions-separated`: requirement elicitation output must distinguish repo/search facts from human-only decisions.
- `REQ-2 confirmation-before-spec-or-code`: ambiguous requests cannot become specs, tickets, or code until the shared-understanding gate is confirmed or an explicit direct-repair contract exists.
- `PLAN-1 plan-review-before-high-risk-execution`: high-risk or multi-session work must have independent plan review before execution is claimed.
- `PLAN-2 research-prototype-before-spec-when-unknown`: if the implementation shape is materially unknown, create research/prototype work before executable tickets.
- `REV-1 blocking-review-scope`: blocking review findings must tie to correctness, stated requirements, owner-doc contracts, security, data integrity, or material maintainability.
- `REV-2 review-receipt-externalized`: local review results for PR-bound work must be recorded outside transient chat context.
- `YT-1 caption-variant-before-asr`: caption selection must try compatible language variants before ASR fallback.

## Reconciliation

This audit does not replace `docs/development/BUILDER_CAPABILITY_PORTFOLIO.md`; it reinforces its existing recommendations around semantic diff review, doc reconciliation, and spec repair. It also aligns with `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`, which already identifies the relevant implicit components.

No GitHub issues, skills, product specs, or runtime behavior were created or changed by this audit. Promotion to executable backlog requires owner approval.
