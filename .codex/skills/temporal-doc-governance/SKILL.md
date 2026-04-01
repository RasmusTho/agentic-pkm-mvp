---
name: temporal-doc-governance
description: "Audit and update time-sensitive docs such as STATUS, ROADMAP, rollout docs, and other temporal control surfaces so they stay aligned with delivered reality."
---

# Temporal Doc Governance

Use this skill when the task is to audit or update documentation with a strong temporal component.

Typical targets:

- `docs/STATUS.md`
- `docs/ROADMAP.md`
- `docs/DOCS_INDEX.md`
- rollout, track, runbook, and current-state docs
- any doc that can drift because code, issues, runtime posture, or operational state changed

## First context to load

- Read `AGENTS.md` first.
- Read `docs/DOCS_INDEX.md` to identify the owner doc and active role.
- Read `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md` for semantic posture.
- Read `docs/templates/DOC_TEMPLATE.md` for required metadata fields.
- If the task is docs-only, follow `.codex/skills/docs-authoring/SKILL.md`.
- If backlog or GitHub state is involved, also use `.codex/skills/backlog-reconciliation-drift-audit/SKILL.md`.

## Audit model

Treat temporal drift as a mismatch between a document's current claims and one or more of:

- shipped code
- runtime/operator surfaces
- open Issues / Project state / merged PRs
- other owning SoT docs
- elapsed time since the last explicit verification

For each target doc, classify:

- `temporally stable`
- `review due`
- `likely stale`
- `historical only`

## Required metadata posture

Time-sensitive docs should carry or inherit these fields near the top:

- `Temporal class`
- `Review cadence`
- `Source of truth`
- `Last reviewed`
- `Last verified against`

Use these classes:

- `timeless` — concept contracts and low-drift principles
- `operational` — current runtime/health/startup/current-state docs
- `strategic` — roadmap and sequencing docs
- `snapshot` — point-in-time reports, delivery snapshots, or status captures

## Update rules

- Prefer correcting current-state claims over rewriting large sections.
- Keep `ROADMAP` forward-looking; move delivered truth into the owner/current-state doc.
- Keep `STATUS` explicitly operational; remove roadmap-like language when reality is already shipped or no longer active.
- If a claim cannot be verified, mark the uncertainty instead of presenting it as current truth.
- Update `Last reviewed` whenever the doc is intentionally checked.
- Update `Last verified against` with the most local concrete verification anchor available.
- If a document is no longer an active truth surface, reclassify it as `Historical` or `Legacy`.

## Minimal output format

When auditing, report:

1. Documents reviewed
2. Drift findings
3. Proposed updates
4. Residual uncertainty

When updating, also report:

1. Which claims were rewritten
2. Which metadata fields were refreshed
3. Which items remain intentionally unverified
