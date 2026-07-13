State: Completed advisory research specification for parent validation hub #3194; parent closure remains a post-merge lifecycle action. No runtime capability, adapter, ingestion path, schema, ADR, or product decision is enacted.
Doc role: Target-state research specification directory
Authority: Owns the completed seven-child advisory research sequence and no-ADR outcome under #3194; subordinate to current Product owner docs, boundary charters, contracts, and any later accepted ADR.
Owner: AI Conversation Intelligence research roadmap (#3194)
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-07-13

# AI Conversation Intelligence Research Roadmap

## Capability boundary

This directory records the completed research that was needed to decide whether and how externally
stored AI conversations might become provenance-bound candidate material in Yggdrasil. It does not authorize
acquisition, ingestion, normalization, memory promotion, HKA mutation, provider authentication, or
runtime implementation.

The already delivered inputs are:

- [input-source options](../research/AI_CONVERSATION_INTELLIGENCE_INPUT_SOURCES.md) (#3195);
- [conceptual conversation data model](../research/AI_CONVERSATION_INTELLIGENCE_DATA_MODEL.md) (#3196);
- [knowledge taxonomy](../research/AI_CONVERSATION_INTELLIGENCE_KNOWLEDGE_TAXONOMY.md) (#3197).
- [privacy, security, and data-ownership baseline](../research/AI_CONVERSATION_INTELLIGENCE_PRIVACY_SECURITY_AND_DATA_OWNERSHIP.md) (#3595).
- [adapter architecture options](../research/AI_CONVERSATION_INTELLIGENCE_ADAPTER_ARCHITECTURE_OPTIONS.md) (#3596).
- [feasibility prototype scope](../research/AI_CONVERSATION_INTELLIGENCE_FEASIBILITY_PROTOTYPE_SCOPE.md) (#3597).
- [research summary and decision gate](../research/AI_CONVERSATION_INTELLIGENCE_RESEARCH_SUMMARY.md) (#3598; no ADR authored).

## Completed research tasks and execution order

The serial sequence is complete. The final [research summary and decision gate](RESEARCH_SUMMARY_AND_DECISION_GATE.md)
reconciles all research, explicitly defers or discards future work, and records that no ADR is mature
or authorized.

The feasibility scope is delivered but no experiment has run. None of the seven artifacts grants
runtime or acquisition authority.

## Cross-task invariants / interaction safety

- Raw provider material, normalized projections, derived candidates, MEM records, and HKA remain
  distinct authority classes throughout the sequence.
- Provider-specific fields stop at EBF-facing research seams and do not become HKA/SIP/GOV
  contracts by documentation alone.
- Every derived claim retains exact source-span lineage and explicit missing/unknown posture.
- Consent, scope, sensitivity, retention, deletion, and redaction constraints flow forward into
  adapter and prototype recommendations; later tasks may strengthen but not silently relax them.
- Partial deletion is not treated as complete while attachments, logs, caches, derived copies, or
  receipts still duplicate semantic content.
- A task is terminal only after its advisory artifact is on `main`, its issue is closed, and its
  validation and owner-doc receipts are present on #3194.
- If a downstream task is blocked or fails, upstream research remains advisory evidence only; it
  grants no runtime or acquisition authority.

## Verification path

Each task produces one advisory research document under `docs/research/`, registers it in
`docs/DOCS_INDEX.md`, passes docs guard and targeted anchor checks, and receives independent review
on the exact PR head. Parent #3194 holds the post-merge validation receipts.

## Validation / acceptance path

Parent #3194 may close only after all seven research children are delivered, the final summary
reconciles conflicts and residual risks, any executable future work is represented by bounded
issues, owner-doc/transition-debt/fitness outcomes are resolved, and the parent closure receipt
passes `docs/development/PARENT_ISSUE_CLOSURE.md`.

An ADR is not itself an acceptance requirement. If the evidence does not support a mature,
authorized architecture decision, the summary remains advisory and records the exact missing
decision or evidence without inventing a ruling.

## Relationship to GitHub issues

- Parent validation hub: #3194 (remains blocked only until final post-merge receipts, run-state, and
  parent-closure checks pass).
- Delivered research: #3195, #3196, #3197, #3595 (privacy/security/data ownership), #3596
  (adapter architecture options), and #3597 (feasibility prototype scope; no experiment executed).
- Final delivered child: #3598 (research summary/ADR gate; advisory no-ADR outcome). Parent closure is
  a separate post-merge lifecycle action and does not authorize any deferred capability.

## Non-goals

- No real conversation export, personal transcript, credential, attachment, or provider payload is
  committed to the repository.
- No adapter, port, schema, migration, event, API, runtime service, policy engine, classifier, or UI
  is implemented.
- No legal advice or claim of regulatory compliance is provided.
- No provider is selected as canonical and no research recommendation becomes shipped truth.
