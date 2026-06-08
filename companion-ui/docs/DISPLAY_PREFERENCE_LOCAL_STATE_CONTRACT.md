---
name: Companion UI Display Preference Local-State Contract
description: Contract for local, non-authoritative display/listening preference state and byte-unchanged canonical Markdown
doc_role: Local-state contract
authority: Binding contract for local display/listening preference state in Companion UI. Canonical artifact authority remains with the vault; this contract owns only the local-UI-state boundary. Where it disagrees with WORKSPACE_STATE_CONTRACT.md on the local-state home, that contract wins.
owner: Companion UI / product architecture
last_reviewed: 2026-06-07
source_contracts:
  - companion-ui/docs/WORKSPACE_STATE_CONTRACT.md
  - companion-ui/docs/UI_RUNTIME_BOUNDARIES.md
  - docs/ARCHITECTURE.md
  - docs/COMPANION_UI_COGNITIVE_LOAD_OPERATING_MODEL.md
governing_issue: "#1643; #1675; new local-state item under #1638"
implementation_state: contract_target_verify_storage_home
---
State: Contract for local display/listening preference state. Storage home remains `WORKSPACE_STATE_CONTRACT.md` unless a later owner contract supersedes it. Captures the contract as of 2026-06-07.

# Companion UI Display Preference Local-State Contract

## Purpose

Display and listening preferences are Local UI state. They re-render identical content with no change to meaning, decision, consequence, provenance, or authority. This contract pins what may be re-rendered, where preference state lives, and the guarantee that canonical Markdown is byte-unchanged.

## What may be re-rendered

Local re-rendering of identical content in the read-only Companion projection may affect:

- Note/source body rendering: font, size, line length, spacing, contrast, and theme.
- Proposal and card text typography/spacing/visual separation, but never option text, option count, default selection, or consequence labelling.
- Resurfaced card rendering within server-declared content.
- Listening modality and pacing: read, listen, sequential, bimodal, and speed.

## Preference state storage

- Preference state is local UI configuration, not canonical knowledge.
- It is stored as UI/workspace state governed by `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md`, never in vault Markdown or frontmatter.
- Per-surface overrides may layer on global defaults; reset-to-canonical must remain available.
- The UI shows a local-only indicator whenever a preference diverges from the canonical render.

## Hard guarantees

1. Canonical Markdown and frontmatter hash is identical before and after any display/listening preference change.
2. No display/listening preference call touches save/projection endpoints, receipts, provenance, memory, or interpretation.
3. Preference state is never read as semantic content by memory extraction.
4. Dyslexia-specific fonts, Bionic Reading, and colored overlays are opt-in, off by default, experimental, and never load-bearing.

## RQ-9 application

Display preferences pass RQ-9 only while they remain re-rendering. Reflow, spacing, theme, modality selection, and playback speed are local presentation. "Simplify," "summarize," or "fix spelling in place" are semantic transformations and belong to separately governed flows.

## Acceptance criteria

- Toggling any display preference leaves the canonical file hash unchanged.
- No preference write reaches a save/projection endpoint or the vault.
- A local-only indicator appears whenever a non-canonical render is active.
- Experimental display interventions are off by default and labelled as experimental.

## Fixtures

`display_override` covers local-only badge, per-surface override, and byte-unchanged assertion. The byte-unchanged assertion is the load-bearing regression test.
