State: Accepted (target-state governance decision, 2026-06-22). Re-affirms — does not relax — the existing non-authoritative agent-memory posture and names a quarantined provisional/low-trust tier for direct writes. Enforcement of the trust-tier guard is a future W7 deliverable (W7-MEM-02, #2354); this ADR is words only and changes no runtime code.
Doc role: Decision record (ADR)
Authority: Authoritative for the *decision* that direct-write memory is provisional/low-trust and non-authoritative by default, that lifecycle escalation requires governance or human, and that provisional memory persists through a human-readable provenance-bound provisional memory note (the human-editable primary artifact, not a rebuildable mirror). Semantic authority for memory remains in `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`; the inbound admit-by predicate remains owned by `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md`; per-entity authority flags remain owned by `docs/SEMANTIC_AUTHORITY_MATRIX.md`. This ADR consolidates and re-affirms those owners; it does not redefine them.
Owner: Agent memory / Architecture spine
Temporal class: Durable decision (supersede via a new ADR, do not edit in place)
Source of truth: This ADR plus the owner contracts it re-affirms (`AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`, `CONTEXT_ADMISSIBILITY_CONTRACT.md`, `SEMANTIC_AUTHORITY_MATRIX.md`, `docs/DURABLE_MEMORY_AND_RECALL/README.md`).

# ADR-0025: Memory authority & direct-write policy

**Date:** 2026-06-22
**Status:** Accepted

> **Numbering note.** This decision is labeled "ADR-0017" on its governing issue (#2318), but
> ADR-0015 through ADR-0022 are already consumed on `origin/main` (the SBS operationalization work,
> #2364). ADR-0023 and ADR-0024 are reserved for sibling issue #2317. The next free number is
> **ADR-0025**, used here. The "0017" in the issue title is historical and supersedes nothing.

---

## Context

Part of epic #2314 (RAG/memory decomposition). The provisional/low-trust memory tier the plan needs
is not yet named as a first-class default, and the deprecation/supersession/rollback/forget lifecycle
receipts are unspecified.

The non-authoritative posture this ADR records already exists, in code and in docs, and this decision
**re-affirms it without relaxation**:

- `app/agent_memory/authority_guard.py` defaults `allow_mutation=False` and only ever sets it true
  through an explicit conjunction (see Decision §2);
- `app/agent_memory/candidate.py` hard-blocks unreviewed candidates from working context;
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` :: Authority rules already states memory must
  not become a hidden source of truth and must not silently escalate authority;
- `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md` already defines the inbound admit-by predicate as
  conjunctive, least-privilege, stricter-boundary-wins;
- `docs/SEMANTIC_AUTHORITY_MATRIX.md` already states "Unreviewed memory must never become hidden
  authority" as categorical.

What is missing is a single decision record that (a) names *direct writes* (memory written without
going through the governed candidate → review → promote path — for example a human or agent editing a
provisional memory note directly) as a **provisional/low-trust** tier with an explicit, narrow
admission ceiling; (b) codifies that no runtime agent may silently escalate any memory across its
lifecycle; (c) requires a human-readable, editable, provenance-bound provisional memory note (the
human-editable primary artifact, not a rebuildable mirror) for provisional memory distinct from
materialized promoted notes; and (d) mandates receipts on every lifecycle
transition while keeping the lifecycle ledger non-authoritative for claim truth.

This ADR opens the reserved widening slot in the memory contract **narrowly** — it names a tier and
its admission ceiling; it grants no new write authority. Enforcement of a trust-tier guard is a
separate future deliverable (see Consequences: WriteGuard is health-state-only today).

## Decision

### 1. Memory is non-authoritative by default; direct writes are provisional/low-trust

Agent memory is non-authoritative by default. Human-authored knowledge remains the primary
meaning-bearing surface; memory is supporting material, not the authority layer.

A **direct write** — memory content created or edited outside the governed candidate → review →
promote lifecycle — enters the **provisional / low-trust** tier. Provisional memory is admitted at
**read** and at **cited-proposal** only. It is **never** admitted to **tool-use / APPLY** (the action
tier), regardless of any other signal.

This admission ceiling aligns the inbound predicate in
`docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md`:

- **Axis 2 (admit-by memory class):** the memory class may permit higher tiers in principle, but the
  action tier additionally requires Axis 3 and the outbound `authority_guard`.
- **Axis 3 (admit-by provenance / trust archetype + review state):** inferred or unreviewed material
  admits to **read** and to **cited-proposal**, but never to **action**. Direct-write provisional
  memory is unreviewed by construction and so sits at exactly this floor.

Because the axes are **conjunctive and least-privilege** and the admitted tier is the **lowest (most
restrictive)** tier any axis returns — **stricter-boundary-wins** — provisional memory's
read/cited-proposal ceiling holds even when another axis would individually permit more. This ADR
does not redefine those axes; it records that direct-write provisional memory lands at the
read/cited-proposal floor under them.

### 2. No silent escalation

No runtime agent may auto-promote, auto-deprecate, supersede, or delete memory, and none may silently
raise a memory's authority across its lifecycle. Every lifecycle escalation — **promotion,
deprecation, supersession, deletion** — requires an explicit **governance transition or human
review**. Existence is not permission; authority is gained only through an explicit governance
transition.

This re-affirms the `authority_guard` conjunction in
`app/agent_memory/authority_guard.py::evaluate_memory_authority`: mutation authority
(`allow_mutation=True`) is granted **only** when *all* of the following hold together — the recall use
right is `ACTION_AUTHORIZING`, the candidate review state is `ACCEPTED`, the memory class is in the
action-authorizing set (policy/preference), a concrete action scope is declared, and there are no
blocking conditions (not inferred, not contradicted/rejected, not a non-current
revised/rejected lifecycle state, and not in conflict with human-authored truth). In every other
path `allow_mutation` is `False`. This ADR does not weaken any term of that conjunction.

It also re-affirms the categorical rule in `docs/SEMANTIC_AUTHORITY_MATRIX.md` reading rule 3:
**unreviewed memory must never become hidden authority** — a `candidate`/`unreviewed` agentic memory
artifact may never hold `activatable`/`instructional`/`action_authorizing`, regardless of any other
signal. Provisional direct-write memory is unreviewed and is therefore categorically excluded from
those rights until a governance or human transition promotes it.

### 3. Provisional memory persists through a human-readable, provenance-bound provisional memory note

Provisional memory persists through a **human-readable, editable, provenance-bound provisional memory
note** — the human-editable *primary* artifact for direct-write memory, not a rebuildable projection
of some other durable source. (This is deliberately **not** a "mirror" in the repo's terminology:
`docs/ENVIRONMENTS.md` and the durable-memory owner docs reserve "mirror" for a rebuildable
projection that is never the primary artifact, whereas this surface is itself the artifact a human
authors and corrects.) It is distinct from the materialized promoted notes produced by the governed
`proposal → WriteGuard → receipt → artifact` path. The provisional note exists so provisional memory
stays inspectable and correctable by the human: it carries source/provenance and review-state
markers, it is the surface a human edits when correcting provisional memory directly, and it is
visibly separate from promoted semantic notes so a reader never mistakes a provisional draft for
reviewed truth.

**iCloud (or any sync substrate the provisional note happens to live on) is never an execution bus.**
The provisional memory note is a human-readable persistence and review surface only. Writing to it, or
a sync engine propagating it across devices, must never trigger promotion, escalation, tool-use, or
any state transition. Lifecycle transitions happen only through the governed path with receipts (§4),
never as a side effect of a file appearing or changing on a sync volume.

### 4. Receipts on every lifecycle transition; ledger authoritative for lifecycle state, not claim truth

There are **receipts on every lifecycle transition** (observe, candidate, review, promote, reject,
revise, deprecate, supersede, decay/archive, delete/forget, recall). The receipt ledger is the
accountability record of *what happened to the memory and when*.

> **ledger authoritative for lifecycle state, not claim truth**

The ledger is authoritative for the lifecycle *state* of a memory (its current position in the
lifecycle and the transition history that put it there). It is **not** authoritative for the *truth*
of the claim the memory contains. A memory can be in lifecycle state `promoted` and still be wrong;
promotion records that a governance/human transition occurred, not that the content is correct.
Claim truth continues to come from human-authored knowledge and review, never from the existence of a
ledger entry.

**No live enforcement of this ceiling exists today; the re-affirmation below is normative only.**
`app/write_guard.py` gates vault writes on the health contract (`WRITE_BLOCKED_STATES`) and does not
enforce a memory trust tier. The `authority_guard` re-affirmed in §2 is itself normative-scope only:
`app/agent_memory/authority_guard.py::evaluate_memory_authority` evaluates `PromotedMemory` and does
not gate a provisional/direct-write path. The admissibility contract is likewise unenforced at
runtime — `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md` records that nothing consults it on a live
path (`app/activation/gate.py` does not invoke it). So there is **no live admissibility or trust-tier
enforcement of this ADR's provisional ceiling today**; the policy is binding on new work as a
normative constraint, not by any running guard.

A **trust-tier guard** that enforces this ADR's provisional read/cited-proposal ceiling at the write
boundary is the required future deliverable — **W7-MEM-02**, tracked by **#2354**. This ADR is **words
only**: it sets the policy and the admission ceiling but adds no enforcement code. W7-MEM-02 is
**required before any provisional direct-write producer or reader lands**, so that the first code path
that creates or consumes provisional memory is gated rather than relying on this normative text alone.

## Constraints honored

- Doc/ADR-only. No `app/agent_memory/*`, `app/write_guard.py`, or other code change — enforcement is
  W7 (#2354).
- No APPLY / tool-use / write authority is granted to provisional or low-trust memory.
- The ledger is not made authoritative for claim truth — only for lifecycle state.
- The existing memory owner docs are extended by pointer paragraph, not forked into a parallel
  memory-policy surface.

## Consequences

- The provisional/low-trust tier for direct writes is now a named, first-class default with an
  explicit read/cited-proposal admission ceiling, aligned to CONTEXT_ADMISSIBILITY Axes 2/3 under
  stricter-boundary-wins.
- No-silent-escalation is codified as a decision: promotion/deprecation/supersession/deletion require
  governance or human; the `authority_guard` conjunction and the unreviewed-memory-never-hidden-
  authority rule are re-affirmed, not relaxed.
- Provisional memory has a designated human-readable, provenance-bound provisional memory note (the
  human-editable primary artifact, not a rebuildable mirror) distinct from promoted notes, with the
  explicit rule that the sync substrate is never an execution bus.
- Every lifecycle transition is receipt-bearing, with the ledger authoritative for lifecycle state
  and never for claim truth.
- Enforcement of the trust-tier ceiling at the write boundary is deferred to W7-MEM-02 (#2354);
  WriteGuard remains health-state-only until then. No runtime behavior changes in this ADR.

## When to revisit

Reopen and re-decide (a new ADR) if any of these change:

- W7-MEM-02 (#2354) ships a trust-tier guard whose enforced semantics need to be reconciled with or
  to tighten this policy.
- A future governed owner contract explicitly widens the reserved `may_write` slot in
  `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` for provisional or low-trust memory (this ADR
  does not widen it).
- The product moves to multi-user / hosted operation, changing the provenance and trust assumptions
  for direct writes.

## References

- Epic #2314 — RAG/memory decomposition.
- #2318 — governing issue for this ADR (labeled "ADR-0017"; renumbered to ADR-0025 here).
- #2317 — sibling decision issue (ADR-0023 / ADR-0024 reserved).
- #2354 — W7-MEM-02, the trust-tier guard enforcement deliverable (enforcement deferred there).
- #1903 — Durable Memory and Recall validation hub.
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` :: Authority rules — non-authoritative
  posture and no-silent-escalation (re-affirmed, pointer paragraph added).
- `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md` :: Axis 2 / Axis 3 — conjunctive, least-privilege,
  stricter-boundary-wins admit-by predicate (aligned by reference).
- `docs/SEMANTIC_AUTHORITY_MATRIX.md` :: Reading rules 2/3/5/6 — authority only via governance
  transition; unreviewed memory never hidden authority; stricter boundary wins; lifecycle state is not
  authority (aligned by reference).
- `docs/DURABLE_MEMORY_AND_RECALL/README.md` :: Capability Boundary — governed
  `proposal → WriteGuard → receipt → artifact` materialization (pointer paragraph added).
- `app/agent_memory/authority_guard.py` (`evaluate_memory_authority` — the re-affirmed conjunction).
- `app/agent_memory/candidate.py` (unreviewed candidates blocked from working context).
- `app/write_guard.py` (health-state-only today; trust-tier guard is W7-MEM-02).
