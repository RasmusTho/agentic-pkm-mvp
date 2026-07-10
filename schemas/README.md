# Schemas

JSON Schemas used across the repo. Three groups live here:

- **Operational schemas** (pre-existing): `capture_triage.schema.json`, `merge_arbiter.schema.json`,
  `hygiene_action.schema.json`, `system-settings.schema.json`.
- **Yggdrasil architecture contracts** (foundation backlog
  [#2533–#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533)): the machine-readable form
  of the doctrine, functional ontology, semantic dimensions, and CrossScopeFlow model. These pair
  one-to-one with prose docs under `docs/architecture/` and do **not** implement runtime behavior.
- **`events/` — the event topic schema registry** (KERNEL-08, #2770): `<topic>.v1.schema.json` per
  topic dispatched by `app/workers/outbox_worker.py::_dispatch_topic`. Unlike the two groups above,
  these **are** runtime-enforced: `app/services/outbox.py::write_outbox_event` and
  `app/workers/outbox_worker.py::_dispatch_topic` validate against them via
  `app/events/topic_schema_registry.py` (the `jsonschema` `Draft202012Validator`, the same machinery
  as `app/components/llm/constrained.py`'s LLM output registry). See `docs/EVENTS.md :: Event Topic
  Schema Registry` for the write/dispatch/grandfathering contract.

## Yggdrasil architecture contracts (#2544–#2548)

| Schema | Doc | Object | Issue |
| --- | --- | --- | --- |
| [`_defs.schema.json`](_defs.schema.json) | [semantic-dimensions](../docs/architecture/semantic-dimensions.md) | Shared semantic-dimension value families + common types | #2538/#2544 |
| [`metadata-bundle.schema.json`](metadata-bundle.schema.json) | [metadata-bundle](../docs/architecture/metadata-bundle.md) | `MetadataBundle` — required envelope for every usable object | [#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544) |
| [`context-envelope.schema.json`](context-envelope.schema.json) | [context-envelope](../docs/architecture/context-envelope.md) | `ContextEnvelope` — bounded agent operating context | [#2545](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2545) |
| [`memory-item.schema.json`](memory-item.schema.json) | [memory-model](../docs/architecture/memory-model.md) | `MemoryItem` — advisory machine memory + promotion boundary | [#2546](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2546) |
| [`authority-transition.schema.json`](authority-transition.schema.json) | [authority-transition-flow](../docs/architecture/authority-transition-flow.md) | `AuthorityTransition` — governed durable mutation | [#2547](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2547) |
| [`retrieval-result.schema.json`](retrieval-result.schema.json) | [retrieval-contract](../docs/architecture/retrieval-contract.md) | `RetrievalResult` — candidate evidence/context | [#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548) |
| [`heimdal-control-notes.schema.json`](heimdal-control-notes.schema.json) | [Mimer client contract](../docs/contracts/MIMER_CLIENT_CONTRACT.md) | Published `_heimdal/**` note-kind, path, and field-authority manifest | [#3131](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3131) |

### Conventions

- Draft **2020-12** (`"$schema": "https://json-schema.org/draft/2020-12/schema"`).
- Stable `$id` per file under `https://yggdrasil.local/schemas/` (placeholder host, consistent with
  the existing `example.local` style; the URI is an identifier, not a fetch target).
- Shared value families and common types live once in [`_defs.schema.json`](_defs.schema.json) and are
  referenced by relative `$ref` (e.g. `_defs.schema.json#/$defs/source_role`). This prevents
  duplication and keeps `source_role`, `authority_state`, and `evidence_role` from collapsing across
  contracts. The metadata bundle is embedded by reference where other contracts carry an object's
  metadata (`metadata-bundle.schema.json`).
- Objects are closed (`additionalProperties: false`) with an explicit `extensions` object as the
  bounded evolution point.

### Validation

There is **no formal JSON Schema validation harness in the repo yet** (no resolver wired into CI).
Until one exists:

- every file is valid JSON and parses with Python's `json` module;
- every `$ref` resolves (cross-file by `$id` + internal JSON pointer) — see the structural notes in
  each contract doc;
- the architecture invariants the schemas encode (role orthogonality, provenance/scope requirements,
  memory-not-canonical, retrieval-not-truth, no raw vault access, no denied-scope leak) are pinned
  later by the invariant registry, eval corpus, and xfail skeletons
  ([#2550–#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)).

**Known JSON Schema limits (deferred to #2550).** A few invariants are *cross-field equality or
monotonicity* constraints that declarative JSON Schema cannot express, so they are enforced
structurally where possible and otherwise pinned by the invariant registry (#2550): e.g. a retrieval
candidate's `evidence_role_in_context` must be ≤ its bundle's intrinsic `evidence_role` (the dangerous
memory_item/projection → `evidence` upgrade *is* blocked structurally; the general ≤ rule is a test),
and a referenced `metadata_bundle_ref` must resolve to a bundle whose scope/identity matches the
item. The schemas remove the duplicate-source-of-truth fields wherever they can so these residual
checks are minimal.

The runtime implementation that consumes these contracts is future work (first slice: Capture →
metadata bundle → DRI segment → retrieval prefilter → RCA result → ContextEnvelope).
