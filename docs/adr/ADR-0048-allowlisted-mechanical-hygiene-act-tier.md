# ADR-0048: Allowlisted mechanical-hygiene body edits move to `act` tier (Accepted)

- **Status:** Accepted — ratified by the owner 2026-07-06. The tier-table amendment is enacted in
  `docs/CAPABILITY_CONTRACT_MODEL.md` (`Proportional governance tiers`). The mechanical-hygiene
  engine still ships propose-only until GRADUATED_CURATION slice G2-3 flips it: this ADR makes that
  flip governance-legal; it does not perform it.
- **Ratified:** 2026-07-06 — Rasmus (owner) ratified this ADR; the row + carve-out sentence are
  applied to `docs/CAPABILITY_CONTRACT_MODEL.md`.
- **Date:** 2026-07-05 (proposed); 2026-07-06 (accepted)
- **Deciders:** Rasmus (owner)
- **Relates to:** `docs/CAPABILITY_CONTRACT_MODEL.md :: Proportional governance tiers` (#1881),
  `docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md` (R1 design), audit ruling R1
  (`docs/research/yggdrasil-fable5-audit.md` §IX)

## Context

The #1881 proportional-governance decision, recorded in `docs/CAPABILITY_CONTRACT_MODEL.md`
(`Ratified boundary decisions`, item 1), deliberately holds **body edits to canonical notes at
`ask-you`** even though Git makes them reversible — because direct prose authorship is the human's
primary creative surface. That decision also marked itself *revisitable under the evidence gate*.

Owner ruling R1 (2026-07-05) approved a narrow revisit: **mechanical hygiene** — misspellings,
grammar noise, speech-to-text transcription artifacts, broken links, malformed markdown — may
auto-apply, because these fixes carry no meaning and holding them at the human gate taxes exactly
the user the dyslexia-friendly posture protects (the human is the *least* well-served proofreader of
mechanical noise). Everything semantic remains proposed into the note's `AI-åtgärder` surface.

Amending a ratified tier-table row is a reshape of an owner doc. Per the program's safety rails,
this ADR **proposes** the amendment; only the owner enacts it by ratifying this ADR and applying the
row to `docs/CAPABILITY_CONTRACT_MODEL.md` (which this ADR deliberately does not edit).

## Decision (proposed)

Add **one row** to the #1881 per-flow tier table:

| Flow | `capability_class` | Tier |
|---|---|---|
| Body edit to a canonical note — **allowlisted mechanical-hygiene class** | `governed_execution` (additive-in-spirit: corrects transcription of existing meaning, adds none) | `act` |

The existing row "Body edit to a canonical note → `ask-you`" remains for **everything else**; this
row is a closed-carve-out, not a relaxation of the rule. The ratified-boundary-decision text gains
one sentence noting the carve-out and pointing here.

### Binding conditions (all mandatory; the row is void where any fails)

1. **Closed class allowlist, decided by class — never by confidence.** Only these
   `CurationFinding` classes are eligible (GRADUATED_CURATION §1 owns the enum and its versioning):
   `link.broken_wikilink` (single unambiguous target only), `markdown.malformed_syntax`
   (deterministic repairs only), `frontmatter.schema_violation` (format only, never value
   semantics), `text.misspelling` and `text.transcription_artifact` (both only under the Swedish
   safeguard, condition 4). `text.grammar` is **excluded** initially; promotion requires new
   owner evidence review (GRADUATED_CURATION slice G2-5). Any class not on the allowlist —
   including any future class — is propose-track; unknown classes fail loud.
2. **Never semantic.** An eligible fix restores intended form; it never changes meaning,
   reorganizes, rewords for style, or resolves ambiguity. Where a transform cannot prove this
   mechanically (e.g. two plausible wikilink targets), the finding demotes to propose.
3. **Deterministic application.** Detection may be cognitive; **application is a deterministic
   class-specific transform** re-derived from file content. If the transform cannot reproduce a
   model's suggestion exactly, demote to propose. LLM output is never the direct source of the
   edit (constraint carried verbatim from #1881).
4. **The Swedish safeguard (hard gate, transform-level).** Per GRADUATED_CURATION §3: sv_SE
   lexicon veto (a valid Swedish word-form is untouchable), diacritic invariance (no auto-fix
   may add/remove/substitute å/ä/ö/é), never cross-language (source and result tokens share the
   language verdict), and `mixed`/`unknown` language verdicts demote to propose. These are
   assertions in the transform, not policy prose.
5. **Reversible + receipted, one by one.** One fix = one atomic Git-visible diff = one receipt
   carrying the `finding_id`; `curation revert <finding_id>` restores the prior span. No batch
   opacity. Log + Git is the safety net — the same rationale #1881 used for every `act`-tier row.
6. **Same gates as every tier.** WriteGuard, policy evaluation, event envelope, and receipts apply
   unchanged; `act` names the authorizer, not an exemption.
7. **Evidence gate for growth.** Adding a class to the allowlist (or promoting `text.grammar`)
   requires the #1881 evidence gate: soak data from the propose-only period (confirm/reject
   ratios), negative-safety coverage (the `autofix_sv_lexicon_guard` fixture corpus), and an owner
   decision recorded against this ADR. The allowlist never grows by config drift.

### Enactment sequence (on ratification)

1. Owner marks this ADR Accepted.
2. Owner-doc PR applies the row + carve-out sentence to `docs/CAPABILITY_CONTRACT_MODEL.md`
   (bundled with the enabling implementation PR per the owner-doc-bundling practice).
3. GRADUATED_CURATION slice G2-3 flips the engine from propose-only to `act` for allowlisted
   classes (`AUTOFIX_APPLY` gate), with the `autofix_allowlist_closed`,
   `autofix_reversible_receipted`, and `autofix_sv_lexicon_guard` invariants live in CI first.

## Consequences

- The human stops being the approval bottleneck for zero-meaning fixes, on the surface where that
  cost is highest (dyslexia-friendly posture) — while prose authorship stays human everywhere else.
- The #1881 principle is *sharpened*, not weakened: the bright line moves from "any body edit" to
  "any body edit that could carry meaning", with the meaning-free set enumerated, deterministic,
  reversible, and receipted.
- Risk accepted: a transform bug could mangle text the user won't proofread. Mitigations are the
  Swedish safeguard, per-fix receipts + revert CLI, the propose-only soak before flip, and the
  invariant tests; residual risk is bounded by Git.
- If never ratified: no loss of function — the engine remains a proposer; the tier table stands.

## Alternatives considered

- **Confidence-threshold auto-apply** — rejected (GRADUATED_CURATION §8): confidence gates rot into
  auto-write creep; class gates are auditable.
- **`agent-review` instead of `act`** — rejected: a second cognition reviewing "teh→the" adds cost
  and latency without adding safety a deterministic transform + lexicon veto doesn't already give;
  #1881 reserves `agent-review` for edits carrying risk or provenance ambiguity, which condition 2
  excludes by construction.
- **Leave everything at propose** — rejected by owner ruling R1; it taxes the protected user for
  zero-meaning confirmations and buries real (semantic) proposals in noise.
