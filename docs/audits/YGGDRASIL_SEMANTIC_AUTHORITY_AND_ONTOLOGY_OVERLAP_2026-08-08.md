State: Advisory target-review snapshot, 2026-08-08. Repository evidence baseline: `origin/main` at `593e93f2cfbcce6c17e511731ea6c458d6b0613b`. Reconciliation is enacted only by the owner-document changes shipped with this review; the audit itself is subordinate to those owners. No runtime, schema, migration, rename, or AI-memory change is authorized.
Doc role: Reference (semantic-review target 1 audit snapshot)
Authority: Evidence-based review of the semantic authority graph and the Cognitive Ontology–Functional Ontology overlap. Owner docs and accepted ADRs win on disagreement.
Owner: Architecture spine / CES stewardship
Temporal class: advisory snapshot
Review cadence: superseded by a later accepted semantic baseline or a material change to either ontology owner
Source of truth: cited owner documents at the baseline SHA; reconciled owner-document text after this review
Last reviewed: 2026-08-08

# Yggdrasil Semantic Authority and Ontology Overlap Review

## 1. Charter and outcome

This is target review 1 from the
[`Yggdrasil Ontological, Semantic, and Nomenclature Baseline`](YGGDRASIL_ONTOLOGICAL_SEMANTIC_BASELINE_2026-08-08.md).
It resolves finding F1: the repository had two canonical ontology entry points but no explicit
pair-specific overlap contract.

The review answers four questions:

1. What does the Cognitive Ontology own?
2. What does the Functional Ontology own?
3. How should a reader resolve shared terms and real conflicts?
4. Which minimum owner-doc changes make that route durable?

The accepted answer is:

- the Cognitive Ontology owns general human-first domain meaning;
- explicitly scoped specialist concept contracts own narrower human/domain semantics;
- the Functional Ontology is the Mimer architecture specialization and owns functional-object
  names and system consequences within that declared scope; and
- architecture representation or governance state may narrow the represented subset of a broader
  human concept, but may not redefine the broader concept or make representation a condition for
  its existence.

Two genuine lexical conflicts were found and reconciled in the owner surface:

- functional `Commitment` now means Mimer's durable, accepted representation of the broader human commitment,
  not the complete human concept and not a claim that governance creates the commitment; and
- functional `Source` now means a represented origin entity or locator, explicitly distinct from
  the epistemic `Source Role` an artifact plays in context.

No new ontology, registry, field, schema, control boundary, or implementation task is needed.

### TCD plan

```yaml
tcd_plan:
  task_summary: resolve the semantic authority graph and Cognitive Ontology to Functional Ontology overlap
  assumptions: owner docs remain authoritative; the target review may clarify owners but cannot reshape the SBS or runtime
  complexity: high
  risk: high
  verification_difficulty: moderate
  human_review_burden: low
  defect_blast_radius: high
  budget_pressure: low
  recommended_capability:
    workflow_or_skill: architecture-research -> docs-governance -> docs-authoring
    model_family: Sol semantic owner with bounded Terra evidence workers
    reasoning_effort: xhigh synthesis; low evidence extraction
    tools: repository search, bounded git history, REST GitHub reads, docs validation
    github_context_required: true
  cheapest_acceptable_path: one semantic-owner synthesis plus three source-anchored read-only briefs and one docs-only PR
  escalation_triggers: an owner contradiction requiring SBS reshape, new runtime meaning, or an accepted ADR change
  deescalation_triggers: pair-specific ownership and conflicts resolvable within existing owner documents
  review_gate: evidence anchors, explicit conflict disposition, SBS conformance, docs checks, and current-head CI
```

Fan-out was justified because authority routing, term-level comparison, and historical reader paths
were independent evidence questions. Workers were read-only and returned anchors; the semantic owner
re-read the sources and made the reconciliation.

## 2. Docs Governance Decision

```text
Docs Governance Decision:
- Artifact role: advisory target-review snapshot plus clarification of existing owner docs
- Owner: Architecture spine / CES for the audit; existing semantic owners for the enacted rule
- Action: create one indexed audit; update the existing ownership convention and both ontology entry points
- Traceability: baseline F1 -> this target review -> owner-document reconciliation
- DOCS_INDEX impact: add the audit row and refresh affected routing descriptions
- SBS/interface ownership: conforms to existing SIP/HKA/GOV/CES allocations; no interface or boundary change
- Next skill or no-change receipt: docs-authoring
- Human Exception: none
```

## 3. Baseline authority graph

The review used the following evidence at baseline SHA
`593e93f2cfbcce6c17e511731ea6c458d6b0613b`:

| Question | Baseline evidence | Finding |
|---|---|---|
| Repository routing | `docs/DOCS_INDEX.md:1-3,38-40,64-67,185-192,351` | The semantic-map route led to Cognitive Ontology; the architecture-foundation route led to Functional Ontology. The routes did not explain their relationship. |
| General ontology | `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md:1-16,87-98` | Canonical human-first, implementation-agnostic ontology; specialist concept contracts win only within explicit narrower scopes. |
| Functional objects | `docs/architecture/functional-ontology.md:1-33` | Canonical names and system consequences for Mimer functional objects, subordinate to doctrine and SBS. |
| Generic precedence | `docs/CONCEPTS/DEFINITION_OWNERSHIP.md:29-60` | More-specific owner wins in its explicit scope; general ontology wins otherwise. Functional Ontology was not classified under this rule. |
| Semantic integration | `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md:28-45` | Layer 1 named Cognitive Ontology and specialist concept owners but omitted Functional Ontology. |
| Target structural ownership | `docs/SYSTEM_BREAKDOWN_STRUCTURE.md:595-703`; `docs/architecture/SBS_OPERATING_MODEL.md:28-33,42-59` | SIP owns target semantic identity/provenance/ontology continuity, HKA durable human knowledge, and GOV authority decisions. SBS is target structure, not shipped-runtime truth. |
| Prior program finding | `docs/audits/YGGDRASIL_ONTOLOGICAL_SEMANTIC_BASELINE_2026-08-08.md:273-286` | F1 correctly identified an inferable human/domain versus architecture-functional split that had not been enacted. |

The problem was therefore a bounded routing and owner-overlap defect, not the absence of semantic
governance and not evidence for a replacement ontology.

## 4. Pairwise overlap analysis

### 4.1 Compatible specializations

| Concept area | Human/domain owner meaning | Functional specialization | Verdict |
|---|---|---|---|
| Actor and delegation | Human owns meaning and authority; System Agent is bounded and delegated (`docs/CONCEPTS/COGNITIVE_ONTOLOGY.md:102-134`) | `Principal` and `CapabilityGrant` attach attribution, scope, revocability, and audit consequences (`docs/architecture/functional-ontology.md:78,109-113`) | Compatible specialization |
| Sphere | Overlapping lived belonging and relevance, not a file bucket (`docs/CONCEPTS/COGNITIVE_ONTOLOGY.md:143-161`) | Human-facing life domain that organizes scopes but cannot grant policy (`docs/architecture/functional-ontology.md:47-49,77`) | Compatible; functional row must not replace lived meaning |
| Cross-scope overlap | Shared participation explains real overlap; explicit allowance governs persistent runtime crossing (`docs/CONCEPTS/COGNITIVE_ONTOLOGY.md:220-261`) | `CrossScopeFlow` is the typed, directional, operation-specific grant (`docs/architecture/functional-ontology.md:58-59,113`) | Compatible functional realization |
| Artifact | Broad cognitive class includes persistent and semi-persistent meaning-bearing objects (`docs/CONCEPTS/COGNITIVE_ONTOLOGY.md:263-309`) | `Artifact` is the durable HKA-managed functional object, distinct from segment, projection, result, and storage (`docs/architecture/functional-ontology.md:89-99`) | Functional subset, not a redefinition of all cognitive artifacts |
| Projection | Bounded representation, not the ontological referent (`docs/CONCEPTS/COGNITIVE_ONTOLOGY.md:337-354`) | Rebuildable representation with provenance and non-evidence defaults (`docs/architecture/functional-ontology.md:50-57,124`) | Compatible specialization |
| Episode | Durable observer-relative situation, distinct from context, sensor event, moment, and workspace (`docs/CONCEPTS/COGNITIVE_ONTOLOGY.md:311-335`) | Same definition with owner, metadata, and dimension allocation (`docs/architecture/functional-ontology.md:99`) | Exact semantic overlap plus system consequences |
| Receipt | Human-legible accountability record distinct from trace (`docs/CONCEPTS/COGNITIVE_ONTOLOGY.md:448-466,619-635`) | `AuthorityReceipt` is the GOV-owned receipt subtype for a governed transition (`docs/architecture/functional-ontology.md:60-62,122`) | Compatible subtype |

The Functional Ontology also uniquely defines architecture objects such as `Segment`, `Claim`,
`Concept`, `Relation`, `MemoryItem`, `Proposal`, `CapabilityGrant`, `CrossScopeFlow`,
`ProvenanceEvent`, and `ExecutionEffect`. Their presence does not make the Functional Ontology a
replacement for the human-first layers of commitments, creative work, or metacognition
(`docs/architecture/functional-ontology.md:89-125`;
`docs/CONCEPTS/COGNITIVE_ONTOLOGY.md:468-617`).

### 4.2 Ambiguous mappings made explicit by the ownership rule

- Cognitive `Operational Scope` is the narrower runtime working boundary and remains distinct from
  Sphere and Context (`docs/CONCEPTS/COGNITIVE_ONTOLOGY.md:180-211`). Functional `Scope` is the architecture
  object that carries cognitive-frame, audience, policy, and provenance facets
  (`docs/architecture/functional-ontology.md:39-49,74-81`). The Functional Ontology owns those system consequences;
  it does not absorb the full human Context or Sphere.
- `Cognitive Artifact` is the general class. Functional `Artifact` is the durable HKA-managed
  system-represented subset. A semi-persistent cognitive artifact can therefore exist without
  already satisfying the functional row.
- `Primary Human Artifact` and functional `HumanArtifact` answer different questions: durable
  human legibility versus human authorship/source role. Neither implies the other.

### 4.3 Conflicts reconciled

#### Commitment

The Cognitive Ontology and its specialist Commitment Layer Contract define a commitment as anything
the human experiences as requiring attention, maintenance, progress, decision, follow-up, or closure
(`docs/CONCEPTS/COGNITIVE_ONTOLOGY.md:468-500`;
`docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md:62-85`). The baseline Functional
Ontology instead made human acceptance and governed durable standing constitutive of `Commitment`
(`docs/architecture/functional-ontology.md:107-113`). Those necessary conditions were incompatible.

Resolution: the human/domain definition stays unchanged. The functional row now describes the
durable, accepted Mimer representation of that human commitment and separates the concept's
existence from the representation's accepted/canonical standing. GOV controls the standing of the
representation, not whether the human commitment exists. Existing functional metadata consequences
remain unchanged.

#### Source

The Cognitive Ontology and specialist Artifact/Projection/Source contract define source primarily as
an epistemic role in context (`docs/CONCEPTS/COGNITIVE_ONTOLOGY.md:356-365`;
`docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md:102-128`). The baseline Functional Ontology used `Source`
as an origin object (`docs/architecture/functional-ontology.md:89-99`) without distinguishing the lexical senses.

Resolution: both concepts remain, but they are explicitly different. `Source Role` is the epistemic
role owned by the human/domain ontology. Functional `Source` is a represented origin entity or
locator for provenance; it is not a universal intrinsic class for every artifact playing a source
role.

## 5. Accepted owner and reading contract

The durable reading order is now:

```text
human/domain question
  -> Cognitive Ontology
  -> explicitly narrower docs/CONCEPTS contract, when present
  -> Functional Ontology for Mimer object representation and system consequences
  -> semantic dimensions / boundary owner / schema / invariant for realization

architecture-functional question
  -> doctrine + target/current structural owner
  -> Functional Ontology row
  -> Cognitive Ontology or specialist concept owner for upstream human/domain meaning
  -> boundary, contract, schema, runtime, and verification evidence
```

This is not a single total ordering. Different owners answer different questions:

| Question | Owner |
|---|---|
| What exists and what does it mean in the human second-brain domain? | Cognitive Ontology or explicit specialist concept contract |
| Which Mimer functional object represents it and what must not collapse? | Functional Ontology |
| Which target control boundary owns the consequence? | SBS and boundary charter |
| What is shipped now? | Current architecture, status, code, and tests |
| How is it serialized or validated? | Specialist contract/schema |
| What is authoritative or admissible? | GOV and authority contracts; ontology alone grants no authority |

## 6. Invariant disposition

The baseline candidate `SEM-05` — every canonical term has a resolvable owner and overlap rule — is
now satisfied for this ontology pair by the owner-document reconciliation. It remains a `DOCTOR`
candidate for the wider semantic-review program; this review does not add it to the invariant
registry or create a new CI gate.

The reconciliation also preserves:

- identity versus representation;
- human meaning versus system representation;
- ontology versus authority;
- current runtime versus target SBS; and
- semantic ownership versus document recency.

## 7. SBS and implementation reconciliation

SBS disposition: **conforms**.

The review uses the existing target responsibilities of HKA, SIP, GOV, and CES. It adds no macro
domain, Level-2 control boundary, interface, owner, event, or runtime component. Functional-object
boundary allocation remains subordinate to the SBS. Current implementation is unchanged; the review
does not convert a target ontology row, metadata field, schema, or test reference into a shipped
runtime claim.

## 8. Issue and backlog reconciliation

No implementation or cleanup Issue is created.

- Closed foundation epic #2533 and semantic-map epic #1363 remain historical delivery evidence; this
  review clarifies their owner relationship rather than reopening them.
- Open Issue [#3957](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3957) owns a narrower trim of
  `docs/ARCHITECTURE.md`. It does not own ontology precedence or the two term conflicts, and this
  review does not alter its scope.
- No open PR at publication preparation claimed this target-review surface. Publication must repeat
  that overlap check immediately before PR creation.

The accepted changes are already bounded owner-document edits, so `feature-breakdown` would add
ceremony without producing executable work.

## 9. Review state after reconciliation

```yaml
accepted_baseline:
  evidence_sha: 593e93f2cfbcce6c17e511731ea6c458d6b0613b
  semantic_authority: distributed owner-doc graph with pair-specific ontology routing
completed_review_targets:
  - system-wide semantic governance baseline
  - semantic authority graph and Cognitive Ontology to Functional Ontology overlap
accepted_decisions:
  - Cognitive Ontology owns general human-first domain meaning
  - specialist concept contracts own narrower declared human/domain scopes
  - Functional Ontology owns Mimer functional-object names and system consequences in its architecture scope
  - functional representation does not define whether the broader human concept exists
  - Source Role and functional Source are distinct
  - functional Commitment represents but does not create the human commitment
resolved_findings:
  - F1 ontology overlap and entry-point ownership
remaining_ambiguities:
  - lifecycle intent of Hugin and Munin in active operational and design surfaces
  - mixed-status Heimdal and candidate-constitution routing
  - schema presence versus production-path enforcement by target
active_review_target: none
next_review_target: ecosystem identity and nomenclature lifecycle
downstream_cleanup_authorized: false
```

## 10. Research-question resolutions

1. **Cognitive owner:** general human/domain concepts and their meaning, with narrower specialist
   concept contracts winning only in declared scope.
2. **Functional owner:** architecture-functional object identity, forbidden conflations, SBS
   allocation, metadata/dimension consequences, and verification links.
3. **Conflict rule:** establish domain meaning first, then reconcile the functional representation;
   governance or representation cannot redefine the broader concept.
4. **Minimum durable change:** one pair-specific rule in Definition Ownership, reciprocal entry-point
   links, Layer-1 routing in the semantic map, and two local term clarifications.

Target review 1 is complete when these owner-document changes are merged. The next ordered review is
ecosystem identity and nomenclature lifecycle: Yggdrasil, Mimer, Heimdal, Hugin, and Munin.
