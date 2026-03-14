State: Working review for docs refactor branch `codex/docs-refactor-structure`.
# Historical Extraction Review

This review compares high-risk historical docs against the active core/reference docs to determine what still has value to extract before archival or deletion.

Reviewed historical docs:
- `docs/SYSTEM_DESIGN_v4.10.md`
- `docs/SYSTEM_YGGDRASIL_Modules_And_Flows.md`
- `docs/SYSTEM_OVERVIEW.md`
- `docs/DIAGRAMS.md`

Compared against current docs:
- `docs/ARCHITECTURE.md`
- `docs/STATUS.md`
- `docs/HUMAN-FLOWS.md`
- `docs/COMPONENTS.md`
- `docs/EVENTS.md`
- `docs/OPERATIONS.md`
- `docs/DOCS_INDEX.md`

## Summary

- Most of the material in these four historical docs is already superseded, duplicated, or outdated.
- The remaining value is mainly:
  - orientation and naming continuity for Yggdrasil modules,
  - a compact system-context/topology summary,
  - a small number of legacy diagrams that may still be worth preserving as background artifacts.
- The historical docs also contain outdated claims that should not survive as active guidance:
  - `WATCHER_AUTO_EXEC` policy text that conflicts with current docs,
  - JSONL outbox framing that predates DB-outbox canon,
  - old Core-6/object/event field names from pre-v5 contracts,
  - old agent and projector/reviewer sequencing.

## Decision Matrix

| Historical doc | Still valuable | Already covered today | Extract target | Proposed disposition |
| --- | --- | --- | --- | --- |
| `docs/SYSTEM_DESIGN_v4.10.md` | Compact system-context view, external dependencies, deployment surfaces, flow-to-infra mapping | Large parts already covered by `ARCHITECTURE`, `COMPONENTS`, `OPERATIONS`, `LLM`, `OBSERVABILITY_STACK`, `DEPENDENCIES` | Extract a short current “System Context / External Surfaces” section into `ARCHITECTURE` or `README`; move topology details into `OPERATIONS`/`INFRASTRUCTURE` if still missing | Archive after extraction; do not delete until topology summary is rehomed |
| `docs/SYSTEM_YGGDRASIL_Modules_And_Flows.md` | Naming continuity for Mimer/Hugin/Munin/Ratatosk/Brokkr/Tyr/Heimdall; high-level module responsibilities | `ARCHITECTURE` now states current Mimer focus and references Yggdrasil, but does not fully capture the module glossary in one place | Extract a short “Yggdrasil module glossary” into `ARCHITECTURE` or `GLOSSARY` | Archive after extraction; likely no need to keep as a first-class doc |
| `docs/SYSTEM_OVERVIEW.md` | Almost none beyond historical sequence/context | Superseded by `CORE_CONTRACT`, `EVENTS`, `RETRIEVAL`, `ARCHITECTURE`, `TESTING` | None | Delete or move deep into archive; no extraction needed |
| `docs/DIAGRAMS.md` | Legacy Mermaid diagrams may still be useful as background if explicitly marked legacy | Current runtime wiring is described in `ARCHITECTURE`; diagrams themselves still reflect older JSONL/projector flows | Possibly keep diagrams under an archive path only, or extract one sanitized current diagram into `docs/diagrams/` later | Archive or move to `docs/archive/`; do not keep in active docs root |

## Per-Document Findings

### `docs/SYSTEM_DESIGN_v4.10.md`

What still has value:
- The C4-style system context is still a good shape for explaining the repo boundary, runtime dependencies, and user-facing surfaces.
- The service/dependency table is useful as a compact orientation aid.
- The “Human Flows -> Infrastructure” mapping is still a useful document pattern.

What is already covered elsewhere:
- Current runtime boundaries and source-of-truth rules are already in `docs/ARCHITECTURE.md`.
- Current component ownership is already in `docs/COMPONENTS.md`.
- Current operational surfaces and startup are already in `docs/OPERATIONS.md` and runbooks.
- LLM/embedding specifics are now better represented in `docs/LLM.md` and `docs/EMBEDDINGS.md`.

What is outdated or risky:
- It still says watcher auto-run remains off unless allowlisted; this conflicts with current `README.md`, `STATUS.md`, and current runtime guidance.
- It still frames Outbox as JSONL-or-DB in a way that predates the DB-outbox-as-canonical position.
- Several port/service descriptions are historical rather than today’s primary runtime path.

Extraction decision:
- Extract only a short current system-context / external-surfaces summary.
- Do not carry over the old topology tables verbatim.

Disposition:
- Archive after extraction.

### `docs/SYSTEM_YGGDRASIL_Modules_And_Flows.md`

What still has value:
- The high-level Yggdrasil naming system and module intent remain useful for orientation.
- The distinction between Mimer as the implemented current focus and other modules as planned/reference context is still useful.
- The Hugin vs Heimdall distinction is a good conceptual boundary.

What is already covered elsewhere:
- `docs/ARCHITECTURE.md` already states that the current architecture focuses on Mimer within the broader Yggdrasil system.
- `docs/HUMAN-FLOWS.md` covers current user-facing flow behavior without needing the old system-map wording.

What is outdated or risky:
- Folder-level descriptions of Mimer internals are partially historical and can be mistaken for current normative structure.
- Some flow descriptions assume planned modules as if they were nearer to implementation than they are today.
- It repeats the outdated watcher auto-run caveat from the old baseline delta block.

Extraction decision:
- Extract a compact glossary-style section only:
  - module name,
  - intended role,
  - whether current, planned, or conceptual.
- Do not preserve the old long-form module map as active reading.

Disposition:
- Archive after extraction.

### `docs/SYSTEM_OVERVIEW.md`

What still has value:
- Mostly historical lineage only.

What is already covered elsewhere:
- Core contract semantics are covered better in `docs/CORE_CONTRACT.md`.
- Event shape and meaning are covered better in `docs/EVENTS.md`.
- Retrieval modes and trust/promotion are covered in current architecture/reference docs.

What is outdated or risky:
- Uses old field names (`id`, `type`) and older “Object payload.core6” framing.
- Uses an older agent sequence (`Reviewer`, `SetEvaluator`, `Projector`) as if it were current.
- The event envelope shown there is not the canonical current one.

Extraction decision:
- None.

Disposition:
- Safe delete candidate once links are removed and archive requirements are confirmed.

### `docs/DIAGRAMS.md`

What still has value:
- The Mermaid source may still help explain historical ingestion/promotion flow evolution.
- The file is useful if the team wants to preserve legacy diagrams for archaeology.

What is already covered elsewhere:
- Current architecture and current runtime boundaries are textually documented in `docs/ARCHITECTURE.md`.
- Current component ownership and flow references are better represented elsewhere.

What is outdated or risky:
- The diagrams encode JSONL outbox as active infrastructure.
- They encode Projector/Reasoning prep flow that is not current baseline runtime truth.
- Keeping this file in the docs root makes it look more current than it is.

Extraction decision:
- No direct extraction into active SoT.
- If diagrams are worth keeping, move them into `docs/archive/` or another explicitly historical location.

Disposition:
- Archive or move; not an active-root doc.

## Recommended Next Execution Step

1. Extract only two small pieces of surviving value:
   - a short current system-context / external-surfaces summary from `SYSTEM_DESIGN_v4.10.md`
   - a short Yggdrasil module glossary from `SYSTEM_YGGDRASIL_Modules_And_Flows.md`
2. Add those extracted summaries to active docs.
3. Move `docs/DIAGRAMS.md` into an archive path or mark it for relocation.
4. Remove or archive `docs/SYSTEM_OVERVIEW.md`.
5. Update any links or index rows that still point at the docs-root historical paths.
6. Update `docs/DOCS_INDEX.md`, `README.md`, and any direct links accordingly.
