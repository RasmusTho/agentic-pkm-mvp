State: The first executable slice is implemented behind a disabled-by-default local flag; no user-facing Lens is shipped.
Doc role: Feature specification
Authority: Defines the ASK provenance-manifest experiment. Subordinate to current retrieval and authorization owner docs for runtime truth.
Owner: Architecture / retrieval

# ASK Provenance Manifest

## Purpose

The ASK Provenance Manifest is a feature-flagged, local-only shadow experiment that records enough identity to compare two grounded ASK executions safely. It is the prerequisite for a future Provenance Diff Lens; it is not the Lens UI and does not claim causal explanations for answer changes.

## Current foundation and boundary

Current typed retrieval contracts do not guarantee canonical content hashes, pipeline identities, admitted-evidence identity, source maps, an end-to-end served-hit span identity, a canonical evidence snapshot, or a durable actual authorization snapshot. Individual lower-level paths may expose partial metadata, but the experiment must capture only identities observed at authoritative runtime boundaries and record every unavailable identity explicitly instead of guessing it.

Manifest capture occurs after normal authorization, retrieval, ranking, and answer synthesis. Failure to capture is fail-open for ASK but fails closed for manifest comparison. Replay always uses current authentication and admission policy; it must never restore historical access.

## First delivery

| Task | Purpose | Status |
| --- | --- | --- |
| [CAPTURE_AND_COMPARE_ASK_PROVENANCE.md](CAPTURE_AND_COMPARE_ASK_PROVENANCE.md) | Capture local immutable manifests and safely compare two executions at the identity granularity actually available. | Implemented behind disabled-by-default flag (#3546) |

Runtime capture is enabled only with `ASK_PROVENANCE_MANIFEST_ENABLED=1` and
requires a local `ASK_PROVENANCE_PRIVACY_KEY`. Records default to restricted
`runtime/agent_memory/ask_provenance_manifests.jsonl`, expire after 14 days,
and are capped at 256 entries. `ASK_PROVENANCE_MANIFEST_PATH` may relocate that
local runtime file, but vault and index destinations are rejected. Capture is
post-answer, bounded, and best-effort: its failure never changes the ASK result.

## Cross-task invariants / interaction safety

- ASK output, ranking, retrieval selection, status, vault content, and index content are byte-for-byte unaffected by enabled capture.
- Manifests contain no raw answer, prompt, note body, credential, or source excerpt. Query and principal correlation use local privacy-safe hashes.
- Comparison requires current authorization to every referenced source. A scope/principal/policy mismatch suppresses evidence details.
- Missing identity produces `indeterminate`, never a stronger provenance, causal, or reproducibility claim.
- Span-level support is prohibited until persisted span identity is wired from indexed source through served hit and synthesis admission.

## Capability acceptance path

The experiment is accepted only after fixture and adversarial evidence proves behavior parity, authorization-safe comparison, bounded retention, and explicit unavailable-identity accounting. A user-facing Lens requires a later decision after those results exist.

## Relationship to GitHub issues

Parent feature issue [#3545](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3545) is the validation hub and remains `agent:blocked` while child [#3546](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3546) delivers the experiment. See [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md).

## Related docs

- `docs/RETRIEVAL.md`
- `docs/FINDING_AND_REORIENTING/README.md`
- `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md`
- `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`
