State: Specification directory — FILED (parent #3314; children #3315–#3319 filed 2026-07-07, all agent:blocked at filing per the uniform closed-loops filing policy). System-level source of truth for building the Daily Briefing capability, the first (owner-ratified priority) of the seven Yggdrasil closed loops identified in `docs/research/yggdrasil-closed-loops-ideation.md`. Grounded in that ideation capture; not itself a plan for the other four loops. GitHub issues are execution artifacts; this spec remains the contract.
Doc role: Capability specification (feature-breakdown lane)
Temporal class: strategic
Review cadence: event-driven (task merges, parent-issue lifecycle)
Source of truth: this directory + the ideation capture it grounds; GitHub issues (#3314–#3319) are execution artifacts, this spec is the contract
Last reviewed: 2026-07-07

# Daily Briefing — Specification

The runtime capability that composes **one generated, provenance-cited, audio-first day-start briefing artifact** from already-live substrate — commitments, the Contextual Relevance Engine's proactive picks, and the decision-receipt log — writes it as a durable vault artifact through the governed write path, triggers its own generation once per day, renders it to speech, and surfaces it as one visual, zero-typing day-start card.

Classification: **Product/Runtime System work** (new derived human-facing surface). Primary subsystem: **HIX** (Human Interaction & Intent — this capability *is* the daily touchpoint/distribution channel); secondary: **RCA** (composes context/evidence from multiple sources into one bundle), **HKA** (the briefing note is a new, vault-durable artifact class), **GOV** (decision receipts consumed as-is), **EBF** (local TTS engine invocation), **DRI** (future: reads the ERE calendar/episode projection).

## Human need this serves

The owner is dyslexic and Swedish/English mixed, and does not want to check panels — he wants **one low-cognitive-load touchpoint per day**, delivered to him (push, not pull), that he can *listen to* rather than read. This is the thin, acknowledged **Reflect** arc stage (`docs/COGNITIVE_PROSTHESIS_CHARTER.md` §2: "review → recalibrate; learn") and the audio-first, visual-pick interface posture that governs every human-facing surface in this system (`docs/HUMAN-FLOWS.md` §0; no typed input, no manual paths).

## Capability boundary

The briefing is a **derived artifact, never a source of truth**. Every fact in it already lives durably somewhere else (a commitment artefact, a materialized Moment, a decision receipt, and — once unblocked — an Episode note); the briefing only assembles, provenance-links, and distributes. It is regenerable at will and disposable without data loss: deleting or losing every briefing note ever generated loses zero human-authored or human-accepted knowledge.

Strategically, this capability is also the **distribution seam** the Episode Resolution Engine deliberately declined to own. ADR-0054 / `docs/EPISODE_RESOLUTION_ENGINE/README.md` excludes egress surfaces (notifications, TTS playback) from the ERE boundary on purpose; Daily Briefing is the other side of that seam. It is also the first consumer-shaped distribution channel the other four closed loops (`docs/DECISION_CALIBRATION/`, `docs/STANDING_QUESTIONS/`, `docs/EPISODE_DEBRIEF/`, `docs/MIMER_VOICE_LOOP/` — none built yet) are expected to deliver through once they land: a future decision-revisit prompt, a standing-question update, or an episode debrief would each become a new *section* of this same briefing artifact, not a new delivery mechanism. This spec does not build those sections; it names them as future input seams so the composer (BRIEF-01) is not designed in a way that forecloses them.

## Sources consumed (canonical inventory)

| source | status | read path (existing, unmodified by this capability) | provenance carried |
| --- | --- | --- | --- |
| commitments (`next_action` / `waiting` / `review_return`) | **live** | `app/services/commitment_persistence.py::load_commitments` → `app/domain/commitments.py::query_next_and_waiting_commitments` | `commitment_id`, `target_ref` |
| CRE relevance picks (materialized Moments) | **live** | `app/relevance/now_surface.py::collect_now_moments` | `moment_id`, `surfaced_refs[].ref` |
| decision receipts | **live** | `app/receipts/decision_receipt_log.py::iter_decision_receipts` | `receipt` entry (`object_id`, `vault_uuid`, `key`, `created_at`) |
| calendar entries / today's episodes | **planned** (blocked on ERE-09 + ERE-02) | `docs/EPISODE_RESOLUTION_ENGINE/CALENDAR_STREAM_ADAPTER.md` registered stream + episode-note projection | episode note ref / calendar UID |
| future: decision-revisit prompts, standing-question updates, episode debriefs | **not designed here** | named as future input seams only — their spec directories (`docs/DECISION_CALIBRATION/`, `docs/STANDING_QUESTIONS/`, `docs/EPISODE_DEBRIEF/`) ship in the same closed-loops wave and each names the briefing as its delivery seam; wiring them in is future work owned by those capabilities | n/a |

A source absent from this table (OS push, email, wake-word/always-listening, briefing-as-write-authority) is excluded deliberately — see Out of Scope.

## Implementation tasks (execution order)

| # | Task | id | Prereqs |
| --- | --- | --- | --- |
| 1 | [COMPOSE_BRIEFING_ARTIFACT](COMPOSE_BRIEFING_ARTIFACT.md) | BRIEF-01 | — |
| 2 | [SCHEDULE_AND_TRIGGER_GENERATION](SCHEDULE_AND_TRIGGER_GENERATION.md) | BRIEF-02 | 1 |
| 3 | [RENDER_BRIEFING_AUDIO](RENDER_BRIEFING_AUDIO.md) | BRIEF-03 | 1 (∥ with 2, 4) |
| 4 | [SURFACE_DAY_START_CARD](SURFACE_DAY_START_CARD.md) | BRIEF-04 | 1 (∥ with 2, 3; degrades gracefully if 3 not yet merged) |
| 5 | [ENRICH_WITH_CALENDAR_EPISODES](ENRICH_WITH_CALENDAR_EPISODES.md) | BRIEF-05 | 1, **external**: ERE-09 (calendar stream, GitHub #3184) + ERE-02 (episode note store) |

Flat order: 1 → {2, 3, 4 in parallel} → 5 (5 is additionally gated on an external prerequisite outside this capability's own delivery chain, so it can land whenever ERE-09/ERE-02 merge, independent of whether 2/3/4 have shipped yet).

Task 4 (the day-start card) is deliberately not hard-blocked on task 3 (audio rendering): it ships with a text-only card and a visibly absent/disabled listen affordance if 3 has not yet merged, then gains the listen button additively when 3 lands — the same out-of-order-deploy tolerance the `COMMITMENT_SURFACING` breakdown used for its route→UI seam. This keeps every task independently mergeable per the feature-breakdown discipline.

## Cross-Task Invariants / Interaction Safety

Multiple tasks read or write the same briefing-note substrate; these invariants hold *across* tasks, including the partial-failure paths:

- **Derived-artifact-only.** The briefing note is never a source of truth and never gains authority. No task may write commitment, decision, or (future) episode state *from* the briefing — every read is one-way, source → briefing. Losing every briefing note ever generated loses zero durable human knowledge.
- **Per-item provenance.** Every rendered line the composer (BRIEF-01) produces carries a resolvable reference back to its source artifact (`target_ref` for commitments, `moment_id`/`surfaced_refs` for CRE picks, the receipt entry for decision receipts, and — once BRIEF-05 lands — the episode/calendar item). BRIEF-03 (audio) and BRIEF-04 (UI card) must preserve that provenance through to the surfaced output, not flatten it into un-attributed prose.
- **Fail-legible partial generation.** BRIEF-01 must name a missing section explicitly rather than silently producing a thinner briefing when one source degrades. BRIEF-02's fallback trigger must not mask a BRIEF-01 degrade as a full success. BRIEF-04's card must visually distinguish "not yet generated", "generated with a named degraded section", and "generated in full" — three different states, never collapsed into one.
- **One generation per day, idempotent.** BRIEF-02 owns the once-per-day guarantee across its two trigger paths (scheduled tick, first-contact-of-day fallback). BRIEF-01 must itself be safe to invoke more than once for the same day without corrupting state (atomic-or-absent write, matching the existing companion-note/commitment-persistence pattern), so that a BRIEF-02 defect that double-fires is at worst a harmless overwrite, never a half-written file.
- **Regenerable without data loss.** Because the artifact is derived, an explicit regenerate (operator action today; a future settings/UI action once one exists) may always re-run BRIEF-01 for the current day and overwrite that day's note. This can never destroy human-owned data (there is none in this artifact), and dated notes (one file per day, not one mutable rolling file) preserve every prior day's provenance links for the future revisit loops named in the ideation capture.

### Partial-failure seams (walked)

- **Compose succeeds, trigger never fires (BRIEF-01 ↔ BRIEF-02).** No briefing note exists for the day. BRIEF-04's card must show an explicit "not yet generated" state — never a stale prior day presented as today's, never a blank/broken card. BRIEF-02's first-contact-of-day fallback (its AC2) is exactly the recovery path for this seam.
- **Compose runs, one source degrades (inside BRIEF-01).** The note is still written, with the degraded section named. BRIEF-04 renders the note that exists, degraded marker visible — a partially degraded briefing is not the same state as "not yet generated" and must not be shown identically.
- **Trigger fires twice the same day (race inside BRIEF-02, e.g. the scheduled tick and the first-contact fallback both fire).** BRIEF-02's idempotency guard must prevent a second automatic compose at its own call site; if that guard were ever to fail open, BRIEF-01's atomic-or-absent write still prevents a corrupted note — the failure mode is "regenerated once more than intended," never "half-written file."
- **Note generated, audio unavailable (BRIEF-01 ↔ BRIEF-03).** The day-start card still renders the full text; the listen affordance degrades to disabled/absent, matching the existing Local-First TTS Contract's provider-unavailable posture. Audio is never on the critical path to reading the briefing.
- **Note generated, UI not deployed or failing (BRIEF-01 ↔ BRIEF-04).** The note still exists in the vault, inspectable directly by the human or by a future consumer; the defect is a display gap, not data loss — the same class of seam bug as `COMMITMENT_SURFACING`'s CI-2 ("persisted but not exposed").
- **Calendar/episode section ships before or after the rest (BRIEF-05, any pairing).** The composed briefing works correctly without this section (it is an explicit non-goal until ERE-09/ERE-02 land) and gains the section additively once the external prerequisite merges — no migration of previously generated dated notes is required.

## Capability acceptance criteria

- [ ] A briefing note composes from all three live sources (commitments, CRE picks, decision receipts), each item carrying a resolvable provenance reference, written through the governed vault-write path. Verify: `tests/briefing/test_compose_briefing.py::test_composes_full_briefing_with_provenance` (BRIEF-01)
- [ ] A partial source failure degrades to a briefing with an explicitly named missing section — never a silently thin briefing. Verify: `tests/briefing/test_compose_briefing.py::test_partial_source_failure_names_missing_section` (BRIEF-01)
- [ ] Generation happens once per day via a scheduled morning tick, with an on-first-contact-of-day fallback when the schedule is missed, idempotent under both paths firing. Verify: `tests/briefing/test_schedule_trigger.py::test_scheduled_tick_generates_once_per_day`, `tests/briefing/test_schedule_trigger.py::test_first_contact_of_day_falls_back_when_schedule_missed`, `tests/briefing/test_schedule_trigger.py::test_duplicate_trigger_same_day_is_idempotent_at_call_site` (BRIEF-02)
- [ ] The briefing renders to mixed sv/en per-segment audio via the existing SpeechPlan/TTS pipeline, one-tap listen, degrading to text-only when TTS is unavailable. Verify: `tests/briefing/test_briefing_audio.py::test_briefing_text_produces_valid_speech_plan`, `tests/companion_ui/test_briefing_listen_affordance.py::test_degrades_to_text_only_when_tts_unavailable` (BRIEF-03)
- [ ] The companion UI surfaces one day-start card (listen + read), zero typing required, read-only, honestly distinguishing "not yet generated" from a degraded or full briefing. Verify: `tests/companion_ui/test_day_start_card.py::test_day_start_card_renders_todays_briefing`, `tests/companion_ui/test_day_start_card.py::test_missing_todays_briefing_shows_pending_state_not_blank` (BRIEF-04)
- [ ] Once ERE-09 (calendar stream) and ERE-02 (episode note store) are live, the briefing gains a today's-calendar/episodes section with the same fail-legible degrade discipline, adding no new episode/calendar logic of its own. Verify: `tests/briefing/test_briefing_calendar_section.py::test_briefing_includes_todays_calendar_episodes_when_stream_live` (BRIEF-05, blocked)
- [ ] Live validation: a real day's briefing generates, lists real commitments/moments/receipts with working provenance links, is audible via one tap, and is visible as one day-start card — receipt posted to the parent issue once filed. Verify: parent-issue validation receipt (mac mini / operator channel)
- [ ] Owner-doc promotion only after acceptance: a writeback naming Daily Briefing as a delivered capability (candidate target: `docs/HUMAN-FLOWS.md` or `docs/STATUS.md`, decided at promotion time) and a row added to `docs/research/yggdrasil-closed-loops-ideation.md` marking loop 1 delivered. Verify: doc writeback at the target chosen at promotion time (not pre-decided here)

## Out of Scope (capability level)

- **OS push notifications** — the ideation capture's roadmap explicitly defers this; the day-start card (BRIEF-04) is a pull-on-open surface, not a push mechanism, until a future capability adds one.
- **Email delivery** — not designed here.
- **Wake-word / always-listening** — out of scope; audio here is one-tap listen-on-demand (BRIEF-03), not an ambient/always-on surface. That belongs to the separate, unbuilt `docs/MIMER_VOICE_LOOP/` loop named in the ideation capture.
- **Briefing as a write-authority surface** — the briefing never gains the power to transition a commitment, mutate a decision receipt, or accept/re-cut an episode. It is read-only distribution, full stop; any future action taken *from* the briefing (e.g. "mark this commitment done") would route through the existing governed transition path for that domain, never through this capability.
- Decision-revisit, standing-question, and episode-debrief *content* — named as future input seams (see Capability boundary) but not designed, scheduled, or built by any task in this directory.

## Relationship to GitHub issues

**Filed 2026-07-07.** Parent feature issue: **#3314** (Backlog, `agent:blocked` live validation hub; see [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)). All five children were filed `agent:blocked`: BRIEF-01 → **#3315** (the dependency-free head — flips to `agent:ready` once this spec PR merges to `main`); BRIEF-02 → **#3318**, BRIEF-03 → **#3317**, BRIEF-04 → **#3319** (all stay `agent:blocked` until BRIEF-01/#3315 merges); BRIEF-05 → **#3316** (stays `agent:blocked` until BRIEF-01/#3315 merges **and** the external prerequisites ERE-09/#3184 + ERE-02/#3177 merge). The spec is the source of truth; issues track pickup state.

## Related Docs

- `docs/research/yggdrasil-closed-loops-ideation.md` — the grounding capture (all five loops, priority ranking)
- `docs/COMMITMENT_SURFACING/README.md` — commitments source + its read-only/degrade-honestly precedent this capability reuses
- `docs/DECISION_RECEIPT_LOG/README.md` — decision-receipt log design and reader
- `docs/CONTEXTUAL_RELEVANCE_ENGINE/README.md` — CRE / Moments source
- `docs/EPISODE_RESOLUTION_ENGINE/README.md`, `docs/EPISODE_RESOLUTION_ENGINE/CALENDAR_STREAM_ADAPTER.md` — the blocked BRIEF-05 prerequisite
- `companion-ui/docs/LOCAL_FIRST_TTS_CONTRACT.md`, `docs/runbooks/RUNBOOK_TTS_PROVISIONING.md` — SpeechPlan/TTS substrate BRIEF-03 reuses
- `docs/SETTINGS_SPINE/README.md`, `docs/SETTINGS_SPINE/SINGLE_DEFAULT_REGISTRY.md` — the tunables posture BRIEF-02 provisionally follows
- `docs/COGNITIVE_PROSTHESIS_CHARTER.md` §2 — the Reflect arc stage this capability serves
