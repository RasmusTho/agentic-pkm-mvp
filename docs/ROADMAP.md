# Roadmap — SoT v4.3.1 → v4.4 → v5.0

_Tracks strategic releases and planned features._

---

## v4.3.1 — Obsidian-first (Delivered / Active baseline)

**Goal:** The vault (Markdown + YAML frontmatter) is the human source of truth. The system does the boring lifecycle work.

Delivered:
- `system-settings.yaml` as canonical runtime policy, with JSON Schema + test validation.
- Promotion Agent:
  - consumes `promote.intent.created`
  - enforces cooldown / idempotence
  - updates frontmatter (`review_state: promoted`)
  - emits `promote.done` and triggers reindex
  - can batch-move files per policy; no Obsidian plugin needed
- Indexer:
  - deterministic embedding
  - upserts by UUID instead of making new random IDs
  - hybrid search boosts good/reviewed/promoted notes
- Outbox-driven propagation:
  - content change → event → indexer → searchable
- Tracing hooks:
  - `start_span(...)` + `trace_id`
  - Jaeger path validated locally
- MergeResolverAgent:
  - semantic 3-way Markdown merge
  - protects UUID and prevents review_state regression
  - keeps references/links
  - penalises giant code dumps in concept notes
  - returns `(merged_text, status, reason)`
- `app/cli/merge_driver.py`:
  - wraps MergeResolverAgent
  - prints merged result + `MERGE_STATUS`/`MERGE_REASON`
  - exit code 0 only if `status=="resolved"`
- NoteHygieneAgent:
  - salvages link-only / low-signal notes
  - archives empty notes via `review_state: archived`
  - moves huge JSON dumps to attachments
  - emits `cleanup.done`

Also:
- Smoke tests (`make smoke`) cover settings schema, promotion roundtrip, merge safety, merge driver CLI, hygiene behaviour.

This is our new normal.

---

## v4.4 — Observability & Conflict Resolution (In progress / Next)

**Goal:** Make the system boring-in-production:
- automatic merge that won't eat data,
- promotion that is observable,
- hygiene that keeps the vault tidy without manual babysitting,
- CI that actually enforces all that.

Planned / ongoing work:
1. **Git merge driver integration**
   - Register `merge_driver.py` as `merge=semantic-md` for `*.md`.
   - Ensure stdout or direct write updates `%A`.
   - Non-zero exit (`prompted` / `conflict`) stops the merge and surfaces `MERGE_REASON`.
   - Add `.gitattributes` and config snippet.
   - Add a CI smoke that shells the driver with BASE/A/B fixtures and asserts:
     - single frontmatter block
     - UUID stable
     - no review_state regression
     - exit code semantics correct

2. **Hygiene as maintenance**
   - Run NoteHygieneAgent post-ingest / post-merge / on schedule.
   - Guarantee every cleanup emits `cleanup.done` with `trace_id` and writes audit.
   - Add smoke asserting we never silently drop meaningful content.

3. **Promotion observability**
   - Promotion Agent already emits spans and `promote.*` events.
   - We’ll add smoke/CI assertions that:
     - promotion produces `promote.done`
     - `trace_id` is present
     - indexer re-embeds the promoted content

4. **CI tightening**
   - Enforce `make smoke` (settings schema, promotion smoke, merge smoke, hygiene smoke) in GitHub Actions on PR.
   - Keep heavier perf/QAS tests (p95 search latency, outbox→index SLA) as manual or nightly to avoid slowing dev loops.

5. **Broker-backed outbox ADR**
   - Write ADR describing Debezium/Kafka-style fan-out.
   - Target SLA: ingestion/promotion intent → indexed+searchable in ≤2s across processes.
   - Do NOT blindly implement broker yet; we just commit to the design + contract.

---

## v4.5 — Governance & Authoring UX (Planned / Future after v4.4 hardening)

Focus:
- More human-friendly merge & review.
- Tighter CI contracts around content quality.

Themes:
- Block-aware / locus-aware HYBRID merges (LLM can selectively splice A + B paragraphs, not just “pick A vs pick B”).
- ASK microflow:
  - If merge can’t auto-resolve confidently, generate a tiny human-facing prompt (“Do you want A, B, or hybrid here and why?”) instead of a blob conflict.
- Golden fixtures for merges and hygiene:
  - Lock in expected behaviour of “good” vs “garbage” notes.
  - CI blocks regressions if heuristics drift.
- Expose merge outcome + rationale to Reviewer / Projector so promoted content always has a provenance trail (“why does this text look like this?”).
- Capture Agents (External → Vault + DB)
  - Introduce first `FileDropCaptureAgent` that monitors import folders or APIs.
  - Writes normalized Markdown into `@Inbox` and mirrors into Postgres.
  - Emits `capture.object.created` events with provenance.
  - Foundation for Email/Chat/Web importers in v4.6+.

---

## v5.0 — Reasoning Alpha (Longer-term)

Goal:
- Add a reasoning / integrity layer on top of SetDB+AMG without letting hallucinations overwrite truth.

Direction:
- Represent certain statements as explicit claims / triples with provenance.
- Add a Guard / Reasoner agent that:
  - validates logical constraints (SHACL-style / rules)
  - detects contradictions
  - flags missing provenance for “facts”
- Neurosymbolic loop:
  - Subsymbolic agents (LLM-based Reviewer, MergeResolverAgent’s arbiter, etc.) propose meaning.
  - Symbolic layer evaluates consistency and policy conformance.
  - Output becomes `decisions` / `audit` / `cleanup.intent.created`, not silent mutation of canonical notes.

This pushes us toward governed knowledge rather than “LLM said so, ship it.”

---

### TL;DR
- **4.3.1** gave us promotion, semantic merge, hygiene, tracing hooks, and smoke tests.
- **4.4** makes that safe and automated in day-to-day dev (git merge driver, hygiene scheduling, CI enforcement, promotion observability).
- **4.5** introduces richer human-in-the-loop authoring UX (hybrid merges, ASK flow, golden fixtures).
- **5.0** brings reasoning/consistency checking as a proper governed layer.
