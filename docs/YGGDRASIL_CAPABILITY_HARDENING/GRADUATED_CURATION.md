State: Specification (design + bounded slices). Advisory until child issues are delivered. Enacts owner ruling R1 (audit §IX, 2026-07-05): mechanical hygiene may auto-fix; anything semantic is PanelAgent suggestions written into the note. Auto-apply is BLOCKED until `docs/adr/ADR-0048-allowlisted-mechanical-hygiene-act-tier.md` (Proposed) is ratified by the owner: **propose-only until ratification, `act`-tier after** (see README owner decision 1).
Doc role: Specification (capability design: graduated curation + synthesis)
Authority: Owns the graduated-curation capability design (G2). Subordinate to `docs/PANEL_AGENT.md` (panel surface + confirmation semantics), `docs/CAPABILITY_CONTRACT_MODEL.md` (capability classes + proportional tiers), `docs/architecture/cross-scope-flow.md`, and the doctrine. It proposes one tier-table amendment via ADR; it does not enact it.
Owner: Architecture / product (Rasmus)
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed — code citations are current reality; design is proposal
Last reviewed: 2026-07-05

# Graduated Curation & Synthesis (G2 · R1)

> **Program note (2026-07-05 second pass):** the Expansion capability (connect + create) now leads
> the program — see `EXPANSION_CONNECT_AND_CREATE.md`. This spec's finding pipeline (G2-1) and
> proposal writer (G2-2) are on Expansion's critical path; the contradiction pass (§4) sequences as
> an Expansion-track sibling. The auto-fix track is independent and gated on ADR-0048.

The audit's largest capability gap: the field is rich at "connect" and "create" (contradiction
surfacing, vault health, synthesis) and does it all by **auto-writing**; our differentiator is doing
it by **proposing** — except for a closed set of mechanical fixes the owner has ruled may auto-apply
(R1). This spec designs both tracks and the wall between them.

## 1. The graduation contract (prose mirror of the schema)

Every curation finding is classified into exactly one of two tracks **by its class, never by its
confidence**:

```
CurationFinding
  finding_id        stable content-derived id: hash(note_uuid, class, span, proposed_change)
  note_uuid         the vault uuid of the target note (never path-derived identity)
  class             one of the closed enum below — decides the track; no LLM output can mint a class
  track             derived: class ∈ MECHANICAL_ALLOWLIST → "auto_fix"  else → "propose"
  span              location (line/range + content_hash of the span) — stale hash ⇒ finding void
  observed          the current text/state (verbatim)
  proposed          the exact replacement text / exact action (never a description of a change)
  evidence          ≥1 resolvable in-vault link for propose-track; ≥2 for contradiction class
  language_verdict  {sv | en | mixed | unknown} + lexicon check result (see §3)
  reversal          for auto_fix: the revert marker id + the receipt id (both mandatory)
```

**Track rules (the wall):**

- `auto_fix` — applies directly at `act` tier: WriteGuard (`assert_writes_allowed`,
  `app/write_guard.py:52-70`) + deterministic writer + one receipt per fix + Git-visible atomic
  diff. **Gated on ADR-0048 (Proposed, not enacted)** — the ratified #1881 decision currently holds
  *all* body edits at `ask-you` ("Body edits stay human", `docs/CAPABILITY_CONTRACT_MODEL.md ::
  Ratified boundary decisions` item 1). `docs/adr/ADR-0048-allowlisted-mechanical-hygiene-act-tier.md`
  proposes the allowlisted-mechanical row plus its binding conditions (closed allowlist, never
  semantic, deterministic transform, Swedish safeguard, per-fix receipt + revert, evidence gate for
  allowlist growth); the owner enacts it, this spec does not. Until ratification, the engine runs
  with `AUTOFIX_APPLY=0` and emits propose-track output for everything; after ratification, the
  allowlisted classes flip to `act` via slice G2-3.
- `propose` — materializes **only** as suggested unchecked checkboxes in the note's `AI-åtgärder`
  panel section, via the existing PanelAgent suggested-checkbox write-back
  (PA2-SUGGESTED-CHECKBOXES / Option B invariants, `docs/PANEL_AGENT.md:126,:132`): always
  unchecked, distinguishable from human-authored actions, idempotent on rerun, `panel.action.logged`
  receipt, and **never executing in the same pass**. Confirmation is the canonical checked-checkbox
  semantics (`docs/PANEL_AGENT.md :: Canonical confirmation semantics`). Per R1 there is **no
  separate UI callout surface** — the note is the review surface.

The class enum is **closed and versioned** (a settings/doc artifact, not code constants scattered):

| Class | Track | Notes |
|---|---|---|
| `link.broken_wikilink` | auto_fix | only when exactly one unambiguous target resolves; else propose |
| `link.dead_external` | propose | removal/replacement is a meaning judgment |
| `markdown.malformed_syntax` | auto_fix | unclosed fences/callouts, broken tables — deterministic repairs only |
| `frontmatter.schema_violation` | auto_fix | key casing/format per `docs/FRONTMATTER.md`; never value semantics |
| `text.misspelling` | auto_fix* | *only under the §3 language gate; else propose |
| `text.grammar` | propose (initial) | promoted to auto_fix only after soak evidence (slice 5) |
| `text.transcription_artifact` | auto_fix* | STT artifacts (duplicated words, mid-word breaks); §3 gate applies |
| `contradiction.claim_conflict` | propose | §4 — requires ≥2 cited sources |
| `structure.orphan / structure.gap / structure.stale_claim` | propose | lint findings that imply meaning |
| anything else | **invalid** | engine fails loud; no default track |

**Non-negotiables inherited, not invented:** proposals are non-authoritative until confirmed
(`docs/PANEL_AGENT.md:37-38`); LLM cognition output is always proposal/clarification class, never
promoted to governed execution without confirmation (`:163`); panel content is not indexed as
knowledge (`:175`).

## 2. Mechanical-hygiene engine (auto-fix track)

Design: a deterministic **fix planner** with an LLM assist *only* for candidate detection, never for
application authority.

- Detection may use cheap local LLM or rules; every candidate is then **re-derived
  deterministically**: the engine recomputes `observed` from the file and constructs `proposed` by a
  class-specific deterministic transform. If the transform cannot reproduce the LLM's suggestion
  exactly, the finding demotes to propose-track. This keeps the `act`-tier writer deterministic (the
  same posture as the Panel deterministic note-writer) — the LLM points, the transform writes.
- **One fix = one atomic write = one receipt.** Receipts append to the note's existing AI status
  callout (bounded, trimmed — same surface as `docs/PANEL_AGENT.md:172`) plus a
  `curation.autofix.applied` outbox event. A batch pass over N notes yields N visible diffs, not one
  opaque commit.
- **Revert marker:** each applied fix records `finding_id` in the receipt line; a
  `curation revert <finding_id>` CLI restores the prior span from Git (log + Git is the safety net —
  the #1881 rationale, verbatim).
- **Idempotency:** re-running the pass over an already-fixed or already-proposed finding is a no-op
  (content-derived `finding_id`; mirrors the panel proposal idempotency contract).
- Concurrency: the engine takes the per-file advisory lock (README owner decision 8) before writing;
  if locking is deferred, the engine is restricted to watcher-serialized invocation.

## 3. The Swedish safeguard (multilingual auto-fix gate)

Threat: an English-centric checker "corrects" valid Swedish — compounds (*sjukvårdsförsäkring*),
definite suffixes (*boken*, *husen*), å/ä/ö — into garbage. Under the dyslexia-friendly posture the
user is *less* likely to catch a bad silent fix, so the gate is hard:

1. **Lexicon veto (deterministic, pre-LLM):** a token present in the sv_SE hunspell dictionary
   (or the note's declared-language dictionary) is **untouchable** by `text.*` auto-fixes,
   regardless of any model's confidence. Same for tokens containing å/ä/ö and for any token that
   sv_SE compound-analysis accepts.
2. **Language verdict per finding, not per note:** the span's language is classified (fast local
   detector); `mixed` or `unknown` verdicts demote `text.*` findings to propose-track. SV↔EN
   code-switching inside one sentence is normal in this vault — demotion, not guessing.
3. **Diacritic invariance:** no auto-fix may add/remove/substitute å/ä/ö/é characters. Ever. Such
   changes are propose-only by construction (transform-level check, not policy prose).
4. **Never cross-language:** a fix may not change the language of the span (e.g. "correct" a Swedish
   word to its English neighbor). The transform asserts source and result tokens share the language
   verdict.

These are transform-level assertions (fail ⇒ demote to propose), covered by the
`autofix_sv_lexicon_guard` invariant with SV/EN fixture pairs (real compound/suffix cases, including
adversarial near-English Swedish: *fakta*, *snabbt*, *event*, *mejl*).

## 4. Contradiction callouts with sourced citations (propose track)

A read-only curation pass (Deep-Agent read-only posture, `docs/ROADMAP.md:256-288` — "Deep Agents
cannot execute or mutate") that cross-references a note against the vault via the retrieval
capability seam (`app/retrieval/capability.py::retrieve`) and emits `contradiction.claim_conflict`
findings:

- Each finding carries the **two conflicting claims verbatim**, ≥2 resolvable source links
  (wikilink or `uuid`-anchored), and a one-line agent interpretation — mapped onto the normalized
  decision-surface proposal format (`docs/PANEL_AGENT.md :: Normalized Decision-Surface Proposal
  Format`) so facts / interpretation / uncertainty / choices stay visibly separate.
- Materialization: an unchecked `AI-åtgärder` checkbox per contradiction with a self-contained label
  ("Motstridigt: X säger A (länk), Y säger B (länk) — markera och bekräfta för att få ett
  förslags-PR i noten"), plus optionally a `[!contradiction]` callout **only after confirmation** —
  the callout itself is a body edit and therefore rides the confirmed action, never the pass.
- Retrieval discipline: the pass consumes `RetrievalResponse` with evidence-role clamping intact —
  a retrieved hit is `background` unless intrinsically `evidence` (`app/retrieval/hybrid.py:21-50`);
  contradictions are *surfaced tensions*, never adjudicated by the agent. Scope prefilter applies;
  cross-scope candidates surface only under an existing flow (`retrieve`+`surface` — a contradiction
  pass never gets `cite`/`import` authority, `docs/architecture/cross-scope-flow.md:60-76`).
- Model routing: the pass is an **offline curation task kind** (`curation.contradiction`) — eligible
  for the paid tier under RUNTIME_MODEL_POSTURE rules (explicit invocation, never tick-driven); runs
  fine on local for small batches.

## 5. Vault-health lint (propose track, read-only)

Ship first (Wave 0) — it is pure read + report and seeds the finding pipeline everything else uses.
Checks (initial eight, mirroring the field's auditor but vault-native): orphan notes, dead wikilinks,
dead external links, missing/invalid frontmatter per `docs/FRONTMATTER.md`, empty/stub notes,
staleness by note-kind policy (`docs/NOTE_KIND_POLICIES.md`), panel blocks with stale option markers,
notes missing `uuid` (advisory only — uuid is lineage metadata, never a render/processing gate).
Output: a lint report note under the system dir (WriteGuard-gated, receipt) + per-note propose-track
findings for actionable items. Builder skill first; runtime scheduling later via G4's tick **only as
a moment**, never as an auto-run mutation.

## 6. Slices

1. **G2-1 Vault-health lint (read-only).** Finding pipeline core (`CurationFinding`, closed class
   enum, content-derived ids) + lint checks + report note. No note-body writes except the report.
   `Verify:` `tests/curation/test_lint_findings.py` (fixture vault → expected findings; idempotent
   rerun), `tests/curation/test_finding_id_stability.py`. Deps: none. **Sonnet.**
2. **G2-2 Mechanical-hygiene engine, propose-only.** Class transforms + language gate + lexicon veto
   + panel suggested-checkbox materialization through the existing PanelAgent write-back. AUTOFIX
   apply path built but hard-disabled (`AUTOFIX_APPLY` absent ⇒ propose).
   `Verify:` `tests/curation/test_hygiene_transforms.py`, `tests/curation/test_sv_lexicon_guard.py`
   (SV/EN adversarial fixtures), `tests/curation/test_propose_only_when_unratified.py`. Deps: G2-1.
   **Sonnet.**
3. **G2-3 Auto-fix activation at `act` tier.** Flip gated on ADR-0048 ratification + the enacting
   owner-doc PR to `docs/CAPABILITY_CONTRACT_MODEL.md` (ADR-0048 :: Enactment sequence). WriteGuard
   action `curation.autofix`, receipts, revert CLI, advisory-lock integration.
   `Verify:` `tests/curation/test_autofix_act_tier.py` (guard-blocked ⇒ loud defer; receipt-before-ack;
   revert restores span), `tests/invariants/test_curation_invariants.py::test_autofix_allowlist_closed`.
   Deps: G2-2 + ADR-0048 ratified + soak evidence from propose-only period. **Sonnet.**
4. **G2-4 Contradiction pass harness.** Retrieval-seam cross-reference, ≥2-citation rule, decision-
   surface formatting, idempotent panel materialization; CLI-invoked (explicit invocation only).
   `Verify:` `tests/curation/test_contradiction_citations_resolve.py`,
   `tests/curation/test_semantic_never_autowrites.py`. Deps: G2-2 writer, G3 identity migration
   (retrieval quality), RUNTIME_MODEL_POSTURE task-kind wiring. **Sonnet** (harness; the pass itself
   is a model run, not code).
5. **G2-5 Grammar-class promotion review (optional, evidence-gated).** After ≥4 weeks of
   propose-track grammar findings, measure confirm/reject ratio; promotion of `text.grammar` to
   auto_fix is a new owner decision with that evidence attached. Deps: G2-3. **Sonnet.**

## 7. Fitness invariants (registry candidates — full entries)

### autofix_allowlist_closed
- **Purpose:** No machine path applies a note-body edit whose finding class is outside the closed
  mechanical allowlist; unknown classes fail loud, they do not default.
- **Affected boundaries:** GOV, HKA (note surface), Panel/curation writers.
- **Expected failure mode:** a new finding class (or raw LLM suggestion) slips into the apply path
  and silently edits meaning.
- **Enforcement:** `static_test` on the class enum + `runtime_test` on the apply seam.
- **Test path:** `tests/invariants/test_curation_invariants.py::test_autofix_allowlist_closed`.

### autofix_reversible_receipted
- **Purpose:** Every applied fix is one atomic Git-visible diff with one receipt carrying
  `finding_id`, and `curation revert <finding_id>` restores the prior span.
- **Expected failure mode:** batch passes producing opaque multi-fix commits, or fixes without
  receipts (silent mutation).
- **Test path:** `tests/invariants/test_curation_invariants.py::test_autofix_reversible_receipted`.

### autofix_sv_lexicon_guard
- **Purpose:** No `text.*` auto-fix touches a lexicon-valid Swedish token, alters diacritics, or
  changes span language; mixed/unknown language demotes to propose.
- **Required fixture:** SV/EN adversarial corpus (compounds, definite suffixes, code-switching).
- **Test path:** `tests/invariants/test_curation_invariants.py::test_sv_lexicon_guard`.

### semantic_curation_never_autowrites
- **Purpose:** Propose-track findings can only materialize as unchecked `AI-åtgärder` checkboxes +
  receipts; no code path from a propose-track finding reaches a body write or governed effect in the
  same pass.
- **Protected principle:** agents propose, human disposes; PA2-FREEFORM proposal/execution boundary.
- **Test path:** `tests/invariants/test_curation_invariants.py::test_semantic_never_autowrites`.

### curation_citations_resolve
- **Purpose:** Every contradiction finding carries ≥2 in-vault source references that resolve at
  materialization time; unresolvable evidence voids the finding (no uncited "trust me" callouts).
- **Test path:** `tests/invariants/test_curation_invariants.py::test_citations_resolve`.

## 8. Rejected alternatives

- **Confidence-threshold graduation** (auto-apply when the model is "sure"): rejected — the track is
  decided by *class*, deterministically. Confidence gates rot into auto-write creep; class gates are
  auditable.
- **A separate review UI for contradictions:** rejected by R1 — the note is the surface; a parallel
  UI would fork the confirmation model the Panel contract already owns.
- **LLM-applied fixes** (model writes the replacement directly): rejected — detection may be
  cognitive, application must be a deterministic transform, or the `act` tier loses its
  deterministic-gate justification.
