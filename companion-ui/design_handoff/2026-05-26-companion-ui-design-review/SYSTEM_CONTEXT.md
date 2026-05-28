# System Context — Yggdrasil / Agentic PKM

## What Yggdrasil is

Yggdrasil (also called Agentic PKM) is a local-first, personal cognitive prosthesis. It is not
a note-taking app, not a productivity dashboard, not a multi-user collaboration platform, and
not an AI assistant with a chat interface. It is a cognitive support environment for a single,
specific user: a senior software architect who lives in the vault daily across Mac, iPad, and
iPhone.

Yggdrasil is three things at once, held together:

1. **A local-first cognitive prosthesis.** It supports cognitive functions a human cannot
   reliably do unaided — durable capture, reorientation across time, retrieval, commitment
   tracking, reflection, source-anchored interpretation — without taking authorship away from
   the human.

2. **A second-brain environment.** Human-authored Markdown artifacts in the vault are the
   primary durable knowledge surface. They are meant to remain readable and editable on disk,
   with any text editor, with or without the system running.

3. **A governed memory and runtime substrate for agents.** System agents act as bounded
   delegates over the vault and machine surfaces under explicit authority contracts. Their
   writes are auditable and leave receipts.

## Human-first framing

The system is designed for one known user. Design must not import patterns that assume
unknown-user product usage: no onboarding flows, no engagement mechanics, no growth loops,
no notification-centric interaction design.

The user thinks at system level. They are deeply fluent in Obsidian, Markdown, and agent
tooling. They are not a consumer and not a novice. The system must respect this without
becoming opaque to a thoughtful observer.

## Single-user, local-first

The system is intentionally single-user. The architecture must not block future multi-user
evolution, but multi-user is not a design driver and no multi-user work is scheduled.

The system runs locally. There is no cloud dependency for core functions. It is accessible
from a private network (LAN or Tailscale) across the user's trusted devices. The Companion
UI is a browser-based web application served by the Yggdrasil host process.

## Vault and Markdown as source of truth

**Vault files are the canonical human knowledge surface.**

Markdown files in the vault are the primary durable artifacts. They:
- must remain readable and editable in Obsidian or any text editor with or without the
  system running,
- must not become dependent on the Companion UI for their meaning,
- must survive any single runtime or technology change.

Frontmatter (YAML between `---` delimiters) holds structured metadata that is human-readable
and human-editable. Wikilinks follow standard Obsidian conventions.

**Stores and databases are machine mirrors, not sources of truth.** SQLite databases, search
indexes, embeddings, and graph projections are rebuildable from the vault. When vault state
and machine state conflict, vault state wins.

Machine writes to the vault — made by agents or the system — go through write guards,
produce receipts, and are reversible. Silent machine edits are a system failure mode.

## Companion UI as cognitive prosthetic, not Obsidian clone

Obsidian is and remains the primary human writing surface. The Companion UI is not an
Obsidian clone or a replacement. It is an **assisted-thinking surface** for cognitive acts
that Obsidian handles poorly:
- orienting within one's own active cognition after interruption,
- reviewing and confirming agent proposals,
- staging AI-suggested edits before applying them,
- reading notes in a context that shows agent activity and provenance alongside them.

The Companion UI's note reading surface must look and feel like Obsidian's Reading View for
supported Markdown constructs. But the goal is not visual parity — the goal is **cognitive
familiarity** that lets the user stay in their thinking without context-switching.

## Panel / governance separation

The Companion UI has two distinct interaction surfaces that must never be collapsed:

**Note body (Canvas surface):** The primary cognitive anchor. Where the user reads, thinks,
and stages edits. The Canvas surface allows the user to co-author the note body with agents
in a governed way, with preview/apply/undo/recovery semantics. Canvas edits route through the
runtime governance pipeline — never directly to vault files.

**Panel / governance rail:** The artifact-local surface where the agent manifests proposals for
what the user likely wants to do with the current note as a system artifact — lifecycle moves,
classifications, commitments, follow-up actions. The user reviews, confirms, corrects, or
rejects. Panel proposals do not auto-execute.

Panel is not a generic inbox. Panel is not Canvas. Panel and Canvas have categorically
different semantics and must be visually and interactionally distinguishable.

## Why cognitive load and friction matter

A cognitive prosthesis only works if using it is less expensive than not using it.

Every interaction that requires the user to figure out what the UI is doing, to recover from
an unexpected state, or to mentally track system state that the UI should be tracking for them
is a failure of the prosthetic purpose. Each failure makes the system less trustworthy and
more burdensome, which causes the user to disengage.

Specific risks:
- **Cognitive load**: requiring working memory for UI structure rather than for thinking.
- **Friction**: any unnecessary step between the user's intent and the system's response.
- **Orientation failure**: not knowing where you are, what is current, what the system did.
- **Resumption failure**: returning after interruption and not being able to reconstruct state.
- **Trust failure**: not knowing whether the system state visible in the UI is accurate.

These are not nice-to-have improvements. They are the conditions under which the system
fulfills its stated purpose.

## Note body as primary cognitive surface

The note body is always the primary surface. The governance rail, outline, and agent activity
are subordinate to it. Any design that competes with the note body for attention — visual
weight, animation, noise — degrades the cognitive value of the system.

The note reading experience must be calm enough for long-form sensemaking and re-reading.
It must not feel like reading inside a dashboard.
