State: Specification (design + bounded slices). Advisory until child issues are delivered. Enacts the 2026-07-05 owner reprioritization: Expansion (connect + create) is the program's north star, pulled forward from the harden-first ordering, behind the existing activation gates. Nothing here claims shipped runtime behavior.
Doc role: Specification (capability design: Cognitive Expansion — Connect + Create)
Authority: Owns the Connect + Create capability design. Subordinate to `docs/COGNITIVE_PROSTHESIS_CHARTER.md` §2.1–2.2 (Maintenance/Expansion model), `docs/EMERGENT_FEATURES_MODEL.md` (composition spine + Expansion Activation Gate), `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md` (inbound admit-by predicate), `docs/CAPABILITY_CONTRACT_MODEL.md` (capability shape + #1881 tiers), `docs/PANEL_AGENT.md` (proposal surface + confirmation semantics), and the doctrine. It adds no authority path; reshape-class needs are flagged for owner ADRs, never enacted here.
Owner: Architecture / product (Rasmus)
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed — code citations are current reality; design is proposal
Last reviewed: 2026-07-05

# Expansion: Connect + Create (the north star capability)

**Why this spec leads the program.** The charter is explicit that Maintenance alone is "a very good
filing cabinet" (`docs/COGNITIVE_PROSTHESIS_CHARTER.md` §2.1); the audit's strongest field signal is
that capture/curate is solved and the value is in connect/create (`docs/research/yggdrasil-fable5-audit.md`
§V–§VI); and the owner has now ruled that connect + create is the program's north star rather than a
harden-first afterthought. This spec makes the dormant Expansion half real: **Connect** (surfacing
non-obvious relationships across notes) and **Create** (producing synthesized outputs the human
accepts into the vault) — both as governed proposals, never as auto-writes.

**The one-vertical-loop, made real.** The roadmap reset froze Expansion behind two preconditions:
a proven vertical loop and a defined admissibility contract. Both are now green — the Panel
confirm→execute loop is live, the admissibility contract is written and enforced at the retrieval
path (KERNEL-10), and the Expansion Activation Gate has already passed its first proof on ASK answer
synthesis (#2022/#2026, `app/activation/gate.py`). Connect + Create is the *second and third* passage
through that same gate, not a new regime. Every design element below composes the seven-element
emergent-feature pattern (`docs/EMERGENT_FEATURES_MODEL.md :: Composition pattern`); nothing bypasses
it.

**Build-on inventory (nothing here is invented from scratch):**

| Existing machinery | Status today | Role in this spec |
|---|---|---|
| Retrieval capability seam (`app/retrieval/capability.py::retrieve`) + scope prefilter, evidence-role clamp, rerank containment (`app/retrieval/hybrid.py:39-50,459-493`) | live | the only way Connect/Create see the vault |
| Admissibility gate (`app/activation/gate.py`, `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md`) | live, proven by ASK #2026 | activation + per-invocation admit predicate for both capabilities |
| CurationFinding pipeline + closed class enum + Panel suggested-checkbox writer (GRADUATED_CURATION §1–2, slices G2-1/G2-2) | this program, Wave H | Connect's materialization substrate |
| Knowledge-compilation contracts: `CompilationDraft`, `CurationCandidate`, `SourceRef`, no-laundering guard (`app/knowledge_compilation/proposal_builders.py::_MACHINE_DERIVATIONS`), admission handoff (`review_admission.py`) | built, dormant (zero callers — `docs/STATUS.md :: Cognitive Expansion`) | Create's artifact + provenance contract |
| Cross-note reasoning (`app/reasoning/multi.py::run_multi_note_reasoning`) | built, dormant | Create's cognition engine (hardened, not rewritten) |
| Governed materialization precedent: memory review-accept writes an agent-promoted vault artifact through WriteGuard with a promotion receipt (`docs/STATUS.md`, #2014 lineage) | live | Create's acceptance path pattern |
| CitationChecker capability (`docs/COMPONENTS.md`) | baseline | Create's provenance validation |
| Proportional-governance tiers (#1881) + PA2 proposal/execution boundary | ratified | the authority frame; nothing here moves a tier |

**Positioning invariant (the moat, restated once):** the entire field does connect/create by
auto-writing into the knowledge base. Ours proposes. If any slice below quietly acquires write
authority to canonical knowledge, it has failed this spec regardless of how useful it is.

---

## 1. Connect — relationship surfacing (candidate-only)

**Cognitive move** (charter §2.1: *insight generation*, *serendipitous discovery*): show the human
relationships across notes they have not made themselves — thematic links, related-but-unlinked
pairs, emerging clusters — as reviewable candidates, grounded in retrieval, never as asserted facts.

### 1.1 Finding classes (extends the closed enum, propose-track by construction)

Connect emits `CurationFinding`s through the *same* pipeline as graduated curation
(GRADUATED_CURATION §1) — one pipeline, one idempotency discipline, one materialization surface.
Three new classes, versioned into the closed enum; the class→track table maps **all** `connect.*`
classes to `propose` and the enum owner doc marks the mapping non-amendable to `auto_fix` (a
`connect.*` class on the auto-fix track is a contract violation, not a config choice):

| Class | What it proposes | Evidence requirement |
|---|---|---|
| `connect.related_unlinked` | a wikilink between two notes with high mutual relevance and no existing link path (direct or 1-hop) | both note refs + ≥1 verbatim supporting span *per side* + the retrieval basis (score class, not raw floats) |
| `connect.thematic_link` | a named theme relating 2..N notes ("these five notes are circling X") | theme label + per-note supporting span + all note refs |
| `connect.cluster_emergence` | an unnamed cluster that has reached hub-worthiness; proposes *creating* an overview/hub note (handoff to Create §2) | cluster member refs (≥3) + pairwise-relatedness basis + a draft theme label marked uncertain |

### 1.2 Discipline (what keeps Connect low-trust)

- **Grounded in retrieval, clamped as candidate.** The pass consumes `RetrievalResponse` with the
  scope prefilter and evidence-role clamp intact; a connect finding's supporting material enters any
  downstream context as `background` at most — machine-derived relatedness is a salience signal,
  never evidence (ADR-0039; `proposal_builders._MACHINE_DERIVATIONS` already encodes exactly this
  refusal — reuse it, do not restate it).
- **Candidate evidence, never authority.** The finding label states the relationship as a question,
  not a fact — normalized decision-surface format (`docs/PANEL_AGENT.md :: Normalized
  Decision-Surface Proposal Format`): observed spans (facts) / suggested relation (interpretation)
  / confidence class (uncertainty) / the checkbox (choice). Accepting the checkbox applies the link
  through the existing governed path at its #1881 tier (a wikilink addition is a cross-note
  structural edit → `agent-review` per the ratified table; the *proposal* carries no tier at all).
- **Scope is hard.** Candidate pairs/clusters are same-scope by default. A cross-scope relation
  surfaces only under an existing `CrossScopeFlow` grant with `surface` operation
  (`docs/architecture/cross-scope-flow.md:60-76`); Connect never receives `cite`/`import`/`export`.
  No grant ⇒ the cross-scope candidate is silently excluded (content-free denial, per KERNEL-10).
- **Cross-lingual is first-class, same-scope only.** On this vault SV↔EN relatedness is a primary
  value of the BGE-M3 migration (G3): a Swedish note and an English note on the same topic *should*
  be proposed as related. Finding labels render in the target note's language (Swedish default per
  the `AI-åtgärder` surface convention); supporting spans are quoted verbatim, never translated.
- **Idempotent + decline-aware.** `finding_id = hash(class, unordered note-uuid set, theme|span basis)`
  — a symmetric pair is one finding; reruns are no-ops (pipeline contract). A **declined** finding
  is remembered (§3) and not re-proposed unless its content basis changed. Serendipity that repeats
  is nagging.
- **Bounded surfacing.** Per-pass caps (max findings per note, max total) — scarcity discipline
  borrowed from the reach-out contract; a connect pass that floods panels is worse than none.

### 1.3 Capability contract (prose mirror; twelve fields per `docs/CAPABILITY_CONTRACT_MODEL.md`)

**Name** `connection_proposal`. **Purpose** surface non-obvious candidate relationships across vault
notes for human review. **Inputs** scope selector (required), note-set or whole-active-scope,
per-pass caps, language policy; admissible context per declared admit predicate (read tier).
**Outputs** `CurationFinding[]` (connect classes) with evidence spans, provenance (capability
name/version, model id if LLM-assisted, retrieval trace id), confidence class. **Allowed callers**
CLI + Panel/companion surfaces + (later) scheduled offers via G4 moments; never a runtime write path.
**Authority class** proposal. **Side effects** panel suggested-checkbox materialization via the G2
writer + `panel.action.logged` receipts; nothing else durable. **Provenance** every finding carries
capability version, cognition metadata (`cognition_metadata.provider/model`), and resolvable note
refs. **Deterministic fallback** relatedness from the deterministic retrieval signals only
(BM25+embedding, no LLM theming) — `connect.related_unlinked` still works; `thematic_link`/`cluster`
degrade to absent, legibly. **Observability** pass receipts (notes scanned, findings emitted /
suppressed-by-decline / suppressed-by-cap), visible in status. **Maturity** Planned. **Replacement**
the finding pipeline is the contract surface; a successor connect engine emits the same classes.

## 2. Create — synthesized outputs (always a proposal)

**Cognitive move** (charter §2.1: *synthesis*, *decision quality*; HUMAN-FLOWS "Compile and curate
memory": *"generated compiled artifacts are not automatically canonical truth; they remain reviewable
outputs until the human decides"* — that sentence is this capability's contract in one line).

### 2.1 Output kinds (closed enum, versioned)

| Kind | What it is | Trigger |
|---|---|---|
| `create.overview` | a synthesis/overview note over a topic, cluster, or note-set (the hub a `connect.cluster_emergence` finding proposes) | explicit human ask, or accepted cluster finding |
| `create.answer_note` | an ASK answer worth keeping, filed as a note with its sources (the "answer becomes knowledge" path — extends the #2026 ASK synthesis proof from ephemeral answer to durable proposal) | explicit human ask only ("save this as a note") |
| `create.digest` | a bounded period digest (what moved, what opened, what went quiet) | explicit ask now; later optionally *offered* via a G4 moment — offered, never auto-run |

Anything else is invalid — the engine fails loud; no default kind.

### 2.2 The draft lifecycle (the heart of the design)

```
trigger (human intent)
  → context assembly through the retrieval seam
      · admissibility gate at cited-proposal tier (declared admit predicate; stricter-boundary-wins)
      · scope prefilter + evidence-role clamp intact; cross-scope material only under a flow with `cite`
  → cognition (run_reasoning / run_multi_note_reasoning — the dormant engines, activated through the gate)
  → CompilationDraft (knowledge_compilation contract: content + SourceRef[] + uncertainty + exclusions
      + ContextAuthorityLimits; built via proposal_builders so the no-laundering guard applies)
  → citation validation (CitationChecker): every SourceRef resolves; quoted spans exist verbatim
      · any unresolvable citation ⇒ the draft is blocked from proposal, loudly — never silently pruned
  → PROPOSAL materialization (act-tier write to STAGING only):
      · draft note written under the system staging area (§2.3) with proposal frontmatter
      · one `AI-åtgärder` acceptance checkbox inside the draft itself (the note is the review surface — R1)
      · receipt: `expansion.create.proposed` with kind, sources, cognition metadata
  → HUMAN decision:
      · edit-then-accept (human edits are authoritative; acceptance covers the edited text)
      · accept ⇒ governed materialization (§2.4)
      · decline ⇒ declined-ledger entry (§3); draft archived/removed, receipt kept
      · ignore ⇒ draft expires after a bounded staleness window (proposal freshness metadata,
        CAPABILITY_CONTRACT_MODEL proposal semantics); expiry is silent-safe, receipt records it
```

### 2.3 Staging: where a draft lives before acceptance

- Drafts are written to a **system staging area inside the vault** (recommended:
  `_system/drafts/` beside the existing system surfaces — final location is owner decision E1, §7)
  so the human reviews them in Obsidian with zero new UI, consistent with the note-is-the-surface
  ruling and the dyslexia-friendly posture (review is reading + one checkbox, never a form).
- Draft frontmatter is unambiguous machine-authorship: `derived_by: synthesis`,
  `authority_state: proposal`, `proposed_by` (capability + model), `sources:` (uuid list), kind,
  created/expires timestamps. A draft is *visibly* not knowledge.
- **Drafts are invisible to retrieval.** Staging content is not indexed as knowledge and cannot be
  retrieved into any context (mirrors "panel content is not indexed as knowledge",
  `docs/PANEL_AGENT.md:175`). This is the anti-laundering keystone: an unaccepted synthesis can
  never become input to the next synthesis, silently compounding machine text into pseudo-knowledge.
  It also composes with `proposal_builders`' guard: even *after* acceptance the note remains
  `derived_by: synthesis` and therefore inadmissible as *authority* for future proposals until its
  review state is human-advanced (`_APPROVED_REVIEW_STATES` discipline) — acceptance makes it
  *knowledge the human owns*, not *evidence the machine may cite as settled*.

### 2.4 Acceptance: governed materialization (the only path to canonical)

- The checked checkbox rides the canonical Panel confirmation semantics — the same confirm→execute
  loop the vertical-loop proof validated. Execution moves/promotes the draft to the human-chosen
  destination (default: a destination proposed in the checkbox label, correctable by the human)
  through WriteGuard, with an `expansion.create.accepted` receipt linking draft → final note →
  sources. Precedent: the memory review-accept governed-materialization path (agent-promoted vault
  artifact through WriteGuard + promotion receipt) — same shape, different artifact.
- Tier: materializing an accepted draft as a **new** note is additive and Git-reversible; the
  acceptance itself is the explicit human act, so no further gate is owed (#1881: the human already
  disposed). Any variant that *modifies an existing canonical note* (e.g. merging a synthesis into
  an existing hub) is a body edit and stays `ask-you` per the ratified table — the checkbox for that
  variant *is* the ask.
- Provenance survives acceptance: the final note keeps its `sources:` list and `derived_by:
  synthesis` + `accepted_by: human` + acceptance receipt id. Synthesis provenance is permanent, not
  a staging artifact. (Frontmatter key additions touch `docs/FRONTMATTER.md` — owner doc; flagged
  as decision E2, §7.)

### 2.5 Multilingual (SV/EN) rules for Create

- Output language = explicit user choice when given, else the dominant source language of the
  admitted set; the draft header states the rule applied.
- Quoted spans are never translated; a synthesis over mixed-language sources says so and quotes each
  source in its own language. Digest/overview *narrative* may be in the human's preferred language
  (Swedish default) while citing EN sources verbatim.
- No machine translation is presented as the source's content, ever — a translation, if asked for,
  is its own labeled derived block. This mirrors the auto-fix diacritic/language gates: language
  identity is content identity.

### 2.6 Capability contract (prose mirror)

**Name** `synthesis_note_proposal`. **Purpose** turn scattered admitted material into a reviewable
synthesized artifact the human may accept into the vault. **Inputs** kind (closed enum), topic /
note-set / question, destination hint, language policy; admitted context per declared predicate at
cited-proposal tier. **Outputs** a staged `CompilationDraft`-backed draft note + proposal receipt;
never a canonical write. **Allowed callers** explicit human intent surfaces (CLI, Panel, companion
ASK "file as note"); `create.digest` additionally offerable via a G4 moment (offer = a checkbox, not
a run). **Authority class** proposal (the acceptance execution is a separate governed-effect flow
owned by the Panel confirm path, not by this capability). **Side effects** staging write (act-tier,
WriteGuard, receipted) + receipts; nothing canonical. **Provenance** SourceRef per synthesized
section; capability version + cognition metadata; citation-validated. **Deterministic fallback**
no LLM ⇒ no synthesis; the capability degrades to a *research-pack-style* deterministic collation
(sources + spans, no narrative) clearly labeled, or declines legibly — it never emits an unsourced
narrative. Provider failure, empty output, and missing input remain explicit degraded reasoning
outcomes with no fabricated claims or inferences; collation stays separate from cognition metadata.
**Observability** proposed/accepted/declined/expired counts + per-draft receipts in
status. **Maturity** Planned. **Replacement** the CompilationDraft + staging + acceptance contract
is the surface; cognition engines behind it are swappable (local or paid per RUNTIME_MODEL_POSTURE —
the executing model never changes what the output may do).

## 3. The declined-proposal ledger (shared mechanism, small)

Connect, Create, and the G2 curation passes all need the same memory: *what did the human already
say no to?* Without it, idempotency only protects against re-proposing the identical finding — not
against re-proposing it every pass forever until accepted. Per the cross-cutting-decomposition rule
this is one mechanism, one slice:

- A derived, rebuildable ledger (`runtime/proposals/declined.jsonl` or PG table — implementation
  choice) keyed by `finding_id`/draft id, recording decline receipts. Deleting it re-enables
  re-proposal, never errors (derived-store posture).
- Every proposal-emitting pass consults it: declined ⇒ suppressed, counted in the pass receipt
  ("suppressed-by-decline: N" — the human can see the system remembering their no).
- Content-based reset: if the finding's content basis changes (spans/hash changed), it is a new
  finding_id and may be proposed again — declining a link once is not declining it after both notes
  were rewritten.
- The ledger is **suppression state, not knowledge**: never indexed, never admitted as context,
  never an input to cognition ("the human dislikes X" must not be inferred from it — that would be
  workflow-learning, a separate gated capability per EMERGENT_FEATURES_MODEL's "agent learns my
  workflow" example).

## 4. Activation through the Expansion Activation Gate

Each capability gets its own activation record per `docs/EMERGENT_FEATURES_MODEL.md :: Expansion
Activation Gate` — declared admissibility, authority class (`proposal` for both), loop precondition
(vertical loop + admissibility contract: both green), reversibility + receipts, observability in
status. The `docs/STATUS.md` Expansion ladder gains two rows (`connection_proposal`,
`synthesis_note_proposal`) moving dormant → gated-active as slices land. The gate stays
deterministic: no model output decides activation. `run_multi_note_reasoning` and
`knowledge_compilation` acquiring their *first runtime callers* is precisely the dormant→live flip
the gate exists to govern — this spec is the gate's second proof, at `proposal` authority (one step
above ASK's read-only proof, still below governed execution).

## 5. Slices (bounded; Sonnet/Opus only — never Fable)

1. **EXP-1 Connect pass: related-unlinked + thematic.** Connect classes into the closed enum
   (propose-track, non-amendable mapping); pass harness over the retrieval seam; caps; panel
   materialization through the G2 writer; CLI-invoked.
   `Verify:` `tests/expansion/test_connect_findings.py` (fixture vault SV+EN: known unlinked pair
   found; linked pair not proposed; cross-scope pair excluded content-free; caps hold; idempotent
   rerun), `tests/invariants/test_expansion_invariants.py::test_connect_candidate_only`.
   Deps: G2-1 (pipeline), G2-2 (writer), G1res-1 (freshness). **Sonnet.**
2. **EXP-2 Declined-proposal ledger.** §3 mechanism + consultation in the G2 + EXP passes + receipts.
   `Verify:` `tests/proposals/test_declined_ledger.py` (declined ⇒ suppressed; content change ⇒
   re-proposable; ledger deleted ⇒ re-proposal not error; ledger never enters context).
   Deps: G2-1. **Sonnet.**
3. **EXP-3 Create engine: overview + answer_note.** CompilationDraft assembly via
   `proposal_builders`, cognition via `run_reasoning`/`multi.py` behind the activation gate,
   citation validation, staging write + proposal frontmatter + in-draft acceptance checkbox,
   expiry sweep.
   `Verify:` `tests/expansion/test_create_draft_lifecycle.py` (draft carries resolving SourceRefs;
   unresolvable citation blocks loudly; staging is not indexed/retrievable; expiry receipts),
   `tests/invariants/test_expansion_invariants.py::test_create_never_autowrites_canonical`,
   `::test_synthesis_carries_source_provenance`. Deps: EXP-1 (retrieval discipline + writer reuse),
   admissibility-gate record. **Sonnet.**
4. **EXP-4 Governed acceptance/promotion.** Checked-checkbox → WriteGuard materialization to the
   human-chosen destination; provenance-preserving frontmatter; decline → ledger; the
   modify-existing-note variant held at `ask-you`.
   `Verify:` `tests/expansion/test_accept_promotion.py` (accept ⇒ note at destination + linked
   receipts + provenance intact; decline ⇒ ledger + no note; edited-then-accepted text is what
   materializes), `tests/invariants/…::test_accepted_note_keeps_provenance`. Deps: EXP-3.
   **Opus** (authority semantics).
5. **EXP-5 Cluster emergence + digest.** `connect.cluster_emergence` → `create.overview` handoff;
   `create.digest` kind; the G4 moment-offer wiring for digests (offer-only).
   `Verify:` `tests/expansion/test_cluster_to_overview.py`, `tests/expansion/test_digest_offer_not_run.py`
   (a moment can only materialize an *offer* checkbox; no draft generation from tick context).
   Deps: EXP-3, EXP-4; G4-1 for the offer path. **Sonnet.**
6. **EXP-6 Activation records + status ladder.** Gate records for both capabilities, activation
   receipts, `docs/STATUS.md` ladder rows, health/status legibility.
   `Verify:` `tests/activation/test_expansion_gate_records.py` (blocked-with-reason when a
   precondition regresses; activation receipt emitted). Deps: EXP-1, EXP-3. **Sonnet.**

Sequencing note: EXP-1..EXP-4 are the vertical loop of this spec — connect finding → human accept →
governed link; synthesis draft → human accept → owned note. EXP-5/6 round it out. The offline
contradiction pass (GRADUATED_CURATION §4, slice G2-4) is a **sibling Expansion pass** — it shares
EXP-1's harness shape and joins this track's sequencing in the program README.

## 6. Fitness invariants (registry candidates — full entries)

### create_never_autowrites_canonical
- **Purpose:** No synthesis output reaches a canonical vault location without a human acceptance
  receipt; the staging area is the only machine-writable destination for Create output, and staging
  is not canonical.
- **Protected principle:** agents propose, human disposes; the field-differentiating moat.
- **Expected failure mode:** a "helpful" slice writes the overview directly to the topic folder, or
  acceptance is inferred from anything other than the human's checkbox.
- **Test path:** `tests/invariants/test_expansion_invariants.py::test_create_never_autowrites_canonical`.

### synthesis_carries_source_provenance
- **Purpose:** Every synthesized draft and every accepted note carries resolvable SourceRefs
  (per-section and note-level); citation-validation failure blocks the proposal loudly; provenance
  survives acceptance permanently.
- **Expected failure mode:** unsourced narrative ships; or sources are pruned at acceptance and the
  note becomes untraceable machine text (the charter's "loss of provenance" failure mode).
- **Test path:** `tests/invariants/test_expansion_invariants.py::test_synthesis_carries_source_provenance`.

### connect_proposals_candidate_only
- **Purpose:** `connect.*` classes map to propose-track by construction (no configuration can move
  them); connect evidence enters downstream context clamped to `background` at most; no connect
  output applies a link without the governed acceptance path.
- **Test path:** `tests/invariants/test_expansion_invariants.py::test_connect_candidate_only`.

### staged_drafts_invisible_to_retrieval
- **Purpose:** Staging-area content is never indexed as knowledge and never retrievable into any
  context; unaccepted machine text cannot compound into future syntheses.
- **Expected failure mode:** silent self-amplification — drafts citing drafts.
- **Test path:** `tests/invariants/test_expansion_invariants.py::test_drafts_invisible_to_retrieval`.

### expansion_requires_activation_record
- **Purpose:** Connect/Create passes run only under a green activation-gate record; a regressed
  precondition yields blocked-with-reason, never a silent run (no third "activate anyway" path).
- **Test path:** `tests/invariants/test_expansion_invariants.py::test_requires_activation_record`.

### declined_findings_not_reproposed
- **Purpose:** A declined finding/draft id is suppressed on later passes until its content basis
  changes; suppression is visible in pass receipts; the ledger itself is never admitted as context.
- **Test path:** `tests/invariants/test_expansion_invariants.py::test_declined_not_reproposed`.

## 7. Owner decisions this spec flags (not resolved here)

- **E1 — Staging location.** Recommended `_system/drafts/` inside the vault (visible in Obsidian,
  zero new UI); alternative is a companion-note-style sidecar area. Low-stakes but touches vault
  layout conventions — owner pick.
- **E2 — Provenance frontmatter keys.** `derived_by`/`sources`/`accepted_by`/`authority_state`
  additions to `docs/FRONTMATTER.md` (ratified owner doc) — needs the normal owner-doc PR when
  EXP-3 lands; keys above are the proposal.
- **E3 — Digest-by-moment.** Whether `create.digest` may be *offered* through a G4 moment once
  G4-1 lands (recommended yes — offer-only is scarcity-safe), and the offer cadence.
- **E4 — Accepted-synthesis review-state semantics.** This spec holds accepted syntheses at
  "human-owned but not machine-citable-as-authority until review-state advances" (§2.3). If the
  owner prefers acceptance to *also* set an approved review state in one act, that is a
  `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`-adjacent call — flagged, defaulting conservative.

## 8. Rejected alternatives

- **Auto-linking above a similarity threshold** (the whole field's default): rejected — confidence
  is not authority; a wrong link silently rewires the human's knowledge graph. Candidate + checkbox
  costs one glance and preserves the moat.
- **A knowledge-graph sidecar store for connections:** rejected — the vault *is* the graph
  (wikilinks); a parallel relation store would be a second source of truth the human can't read.
  Machine-side relatedness lives where it already lives: retrieval indexes, disposable.
- **Synthesis directly into ASK chat with a "save" that writes canonically in one step:** rejected —
  collapses proposal and acceptance into one surface interaction with no draft the human can edit;
  the staging draft is what makes edit-then-accept (real co-authorship) possible.
- **LLM-scored "insightfulness" ranking of connect findings:** rejected for slice scope —
  cap + decline-ledger + human feedback is the honest ranking loop first; a learned ranker is
  workflow-learning and belongs behind its own gate later.
- **Reusing the ASK read-only activation record for Create:** rejected — Create is `proposal`
  authority with a staging side effect; it must pass the gate on its own declaration, or the gate
  stops meaning anything.
