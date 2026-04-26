---
name: Thread Scope, Sphere, and Identity Through Runtime Paths
description: Specify where the separated context dimensions enter, transform, and exit runtime surfaces.
task_id: SSI-02
source_anchor: docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md :: Priority 2b — Scope, sphere, and situated identity as distinct properties (v6.0 enabling)
parent_capability: Scope, sphere, and situated identity as distinct properties
prerequisites: [SSI-01]
depends_on: [DEFINE_CONTEXT_DIMENSION_PAYLOAD_CONTRACT.md]
can_parallelize_with: [EXPOSE_CONTEXT_DIMENSIONS_IN_STATUS_AND_RECEIPTS]
---

# Thread Scope, Sphere, and Identity Through Runtime Paths

## Purpose

Define a bounded runtime threading map so separated context dimensions survive through ingest/orchestrator/panel paths without semantic collapse.

## What This Task Does

- Enumerates runtime entrypoints where context is read.
- Enumerates transformation points where context must preserve dimension separation.
- Enumerates output surfaces where context dimensions must remain explicit.

## Concretely

- Add path map for watcher/orchestrator/panel/receipts surfaces.
- Add explicit "must preserve" checkpoints and failure modes.
- Add compatibility notes for incremental rollout.

## Why This Matters

Without a threading map, implementation can partially preserve dimensions in one path and lose them in another, creating hidden regressions.

## Acceptance Criteria

- [ ] Runtime path map names entry, transform, and output points that touch context semantics.  
  Verify: doc writeback at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/THREAD_SCOPE_SPHERE_IDENTITY_THROUGH_RUNTIME_PATHS.md`.
- [ ] Each path stage includes preservation checkpoints for scope/sphere/identity separation.  
  Verify: doc writeback at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/THREAD_SCOPE_SPHERE_IDENTITY_THROUGH_RUNTIME_PATHS.md`.
- [ ] Incremental rollout and compatibility notes are explicit.  
  Verify: doc writeback at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/THREAD_SCOPE_SPHERE_IDENTITY_THROUGH_RUNTIME_PATHS.md`.

## How to Verify (Pre-Merge)

- `rg -n "entry|transform|output|checkpoint|compatibility" docs/SCOPE_SPHERE_SITUATED_IDENTITY/THREAD_SCOPE_SPHERE_IDENTITY_THROUGH_RUNTIME_PATHS.md`
- Reviewer confirms each AC has explicit corresponding passages.

## Out of Scope

- Implementing runtime code.
- Updating owner-doc support claims.

## Related Docs

- `docs/ARCHITECTURE.md`
- `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md`
- `docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md`

## Related GitHub Issues

- Parent: `docs/SCOPE_SPHERE_SITUATED_IDENTITY/PARENT_FEATURE_ISSUE.md`
- Follow-up implementation issue: to be created from this task spec.

---

## Runtime Threading Map

This section is the deliverable for SSI-02. It maps every runtime entrypoint, transformation
point, and output surface that touches context semantics, and names the preservation checkpoints
that prevent semantic collapse.

The canonical field names used throughout are defined in
`docs/SCOPE_SPHERE_SITUATED_IDENTITY/DEFINE_CONTEXT_DIMENSION_PAYLOAD_CONTRACT.md` (SSI-01):
`scope`, `sphere_memberships`, `situated_identity`.

---

### Runtime paths in scope

Four paths carry context semantics today or will carry them as SSI dimensions are introduced:

1. **ASK / retrieval path** — external query enters via CLI or HTTP, traverses the retrieval layer,
   and returns results filtered and ranked by operational scope.
2. **Panel action path** — panel command enters via CLI, is resolved into a plan, dispatched
   through the orchestrator, executes tool steps, and emits a receipt.
3. **Watcher-triggered automation path** — vault file change is detected, the auto-run gate
   decides whether to proceed, and an orchestrator run is triggered with note-level context.
4. **Orientation path** — orientation runtime assembles a context snapshot for a query or
   a status surface; this is a read-only aggregation path.

> **Note on watcher `scope_glob`:** `app/watcher/` uses a `scope_glob` field to define which
> filesystem paths are watched. This is a filesystem-scope filter, not an SSI operational scope.
> The naming collision is intentional in current code. When SSI `scope` is introduced to watcher
> context, it must use the canonical `scope` field name and must not be confused with `scope_glob`.

---

### Path 1: ASK / retrieval path

#### Entry

| Source | Current field | SSI-01 canonical field |
|---|---|---|
| `ASK_DOMAIN_SCOPE` env var | `domain` / raw env string | → `scope` |
| `bridge_domains` per-document metadata | `bridge_domains` | → cross-scope allowance (not a context dimension; see SSI-01 mapping rules) |
| Sphere and identity | (not present) | → `sphere_memberships`, `situated_identity` (additive) |

Current runtime: `app/retrieval/hybrid.py::_resolve_domain_scope()` reads `ASK_DOMAIN_SCOPE`. This is
the `scope` entry point. No `sphere_memberships` or `situated_identity` fields exist here yet.

**Must preserve checkpoint:** `scope` resolved at entry must flow unchanged to the retrieval
filter. It must not be re-read from a different source mid-path, which would create an implicit
scope switch.

#### Transformation

| Stage | What happens | Preservation requirement |
|---|---|---|
| Domain/scope resolution | `_resolve_domain_scope()` resolves the active scope from env; `_extract_domain(doc)` reads the domain from each document for comparison against the active scope | Rename/alias as `scope` when SSI dimensions are introduced; must not be joined with `sphere_memberships` into one string |
| `bridge_domains` inclusion | Per-document flag that widens the scope filter for specific documents | Must remain a document-level cross-scope allowance, not collapsed into `scope` |
| Sphere filtering (future) | `sphere_memberships` will narrow or weight results within the active scope | Must be applied as an additive filter, not as a replacement for `scope` |
| Identity signal (future) | `situated_identity` may influence ranking or prompt framing | Must remain readable as null; null means "no identity signal", not "default scope" |

**Failure mode — scope/sphere collapse:** treating sphere memberships as equivalent to operational
scope causes retrieval to use sphere filtering as a partition boundary. A note in multiple
spheres may then appear in some scoped queries and not others in a way that violates the one-active-scope invariant.

**Failure mode — scope re-resolution:** if `scope` is not carried through the retrieval call
and instead re-resolved at a later stage from a different env var or request field, retrieval
partitioning may silently diverge from the scope the caller intended.

#### Output

- Retrieval results carry source provenance but do not today surface the active `scope`,
  `sphere_memberships`, or `situated_identity` that shaped them.
- When SSI-03 (status/receipt representation) lands, a retrieval receipt should include the
  active `scope` and, if used, the `sphere_memberships` filter applied. This is out of scope
  for SSI-02 but noted here as the output requirement.

---

### Path 2: Panel action path

#### Entry

| Source | Current field | SSI-01 canonical field |
|---|---|---|
| Panel CLI command | `plan.context` (arbitrary dict) | → `scope` must be a named key |
| Orchestrator step dispatch | `StepContext` | → must carry `scope`, `sphere_memberships`, `situated_identity` explicitly |
| Sphere and identity | (not present) | → additive; must not require structural changes to existing step execution |

Current runtime: `app/orchestrator/runtime.py` extracts `profile_selection`, `flow_ids`, and
`tool_settings` from `plan.context`. The `plan.context` dict is the current structured entry
point for context dimensions.

**Must preserve checkpoint:** when `plan.context` is enriched with `scope`, `sphere_memberships`,
and `situated_identity`, those fields must be forwarded to each `StepContext` in the execution
loop. They must not be consumed by the orchestrator and silently dropped before tool dispatch.

#### Transformation

| Stage | What happens | Preservation requirement |
|---|---|---|
| Plan resolution | `plan.context` is read for profile/flow selection | `scope`, `sphere_memberships`, `situated_identity` must not be stripped during plan resolution |
| Step dispatch | `StepContext` is constructed per step | Must include `scope` and, when present, `sphere_memberships` and `situated_identity` |
| Tool execution | Each tool receives `StepContext` | Tools must read `scope` from `StepContext`, not from env or a separate global |
| Receipt emission | Outbox event is emitted after step | Must carry `scope` (and optionally `sphere_memberships`, `situated_identity`) in the event payload or meta |

**Failure mode — context drop at step boundary:** constructing `StepContext` from `plan.context`
without explicitly forwarding SSI fields means every tool executes with no identity or sphere
signal even when the calling surface had one.

**Failure mode — scope implicit in agent selection:** if the orchestrator maps `scope` to an
agent identifier and then discards the `scope` field, downstream tools lose the scope signal.
Scope must travel alongside agent selection, not be consumed by it.

#### Output

- Panel receipts and outbox events should carry the active `scope` at minimum.
- `sphere_memberships` and `situated_identity` are optional in the initial rollout and may be
  omitted from event meta when not declared — but must not be replaced with a default scope value.
- Format is defined by SSI-03; this path only specifies that the fields must survive to the
  emission point.

---

### Path 3: Watcher-triggered automation path

#### Entry

| Source | Current field | SSI-01 canonical field |
|---|---|---|
| Note frontmatter | `domain` (legacy) or none | → `scope` when declared |
| Watcher config | `scope_glob` (filesystem scope) | → not an SSI field; preserve as-is |
| Sphere and identity | (not present) | → additive; initially absent |

Current runtime: watcher auto-run builds a minimal context from the note's filesystem path and
frontmatter. No `scope`, `sphere_memberships`, or `situated_identity` fields are constructed
today.

**Must preserve checkpoint:** if a note carries a `domain` or `scope` frontmatter field, the
watcher-triggered context must read it as `scope` (not re-mapped to `sphere_memberships` or
dropped). The filesystem `scope_glob` must not be read as the operational `scope`.

#### Transformation

| Stage | What happens | Preservation requirement |
|---|---|---|
| Note frontmatter read | Watcher reads note metadata | `domain` → `scope` migration mapping applies (SSI-01 backward-compatible rule) |
| Auto-run gate | DedupTaskQueue decides whether to trigger | Gate logic must not consume or modify context dimensions; pass them through unchanged |
| Orchestrator trigger | Watcher calls into orchestrator with note context | `scope` from note (if present) must be passed as `plan.context["scope"]`; must not fall back to global `ASK_DOMAIN_SCOPE` for note-level context |
| Step execution | Same as Panel action path (Path 2) | Same preservation requirements apply |

**Failure mode — scope_glob leaking into operational scope:** code that reads `scope_glob` as
the `scope` dimension would assign filesystem-glob syntax as an operational partition filter.
The two fields are distinct and must never be merged.

**Failure mode — per-note scope dropped in batch:** when multiple notes trigger in a batch,
each note's `scope` must be respected independently. Batch processing must not substitute a
single global scope for all notes.

#### Output

- Watcher-triggered outbox events must carry per-note `scope` when available.
- Omitting `scope` from watcher events is acceptable when no scope is declared on the note.
  The absence must be represented as null/missing, not as a default scope string.

---

### Path 4: Orientation path

#### Entry

Orientation (`app/orientation/runtime.py`) assembles a context snapshot from runtime state.
This is a read-path; it does not mutate context dimensions.

| Source | Current field | SSI-01 canonical field |
|---|---|---|
| Active settings / env | `PKM_ENVIRONMENT`, instance config | → operational metadata; not an SSI context dimension |
| Retrieved notes | `domain` on note records | → `scope` when SSI fields are introduced to note records |
| Sphere and identity | (not present) | → additive; orientation may surface them once present |

**Must preserve checkpoint:** orientation must not interpret `sphere_memberships` as an
operational scope filter when assembling its snapshot. Reading sphere data for display or
aggregation is distinct from using it as a retrieval partition.

#### Transformation

Orientation is a read-only aggregation. Context dimensions travel from note records and runtime
state into the orientation snapshot without modification. The main risk is collapse at aggregation:

**Failure mode — sphere collapsed into scope at aggregation:** if the orientation snapshot
reduces note context to a single `scope` field by combining or discarding `sphere_memberships`
and `situated_identity`, the operator loses visibility into the richer context signals.

#### Output

- Orientation snapshots (CLI and HTTP status) are the primary operator-visible surfaces for
  context dimension state. SSI-03 defines the specific fields required.
- For SSI-02: orientation output must not drop or flatten context dimension fields it receives;
  it must forward them unchanged to the status surface layer.

---

### Preservation checkpoints summary

| Path | Entry checkpoint | Transform checkpoints | Output checkpoint |
|---|---|---|---|
| ASK / retrieval | `scope` resolved from `ASK_DOMAIN_SCOPE`; not re-resolved mid-path | `scope` flows to filter; `sphere_memberships` not merged into `scope` | Retrieval receipt includes active `scope` (SSI-03 defines shape) |
| Panel action | `scope`, `sphere_memberships`, `situated_identity` declared in `plan.context` | All three forwarded in `StepContext`; not consumed by orchestrator | Receipt/outbox event carries `scope` at minimum |
| Watcher automation | `domain`/`scope` from note frontmatter; `scope_glob` kept separate | Per-note `scope` carried through auto-run gate and into orchestrator | Per-note outbox event carries `scope` when present |
| Orientation | Note records surface context dimensions; not filtered at read | No modification; collapse at aggregation is the failure mode | Status snapshot surfaces context dimensions unchanged |

---

### Incremental rollout and compatibility notes

The SSI dimensions are introduced additively. No existing runtime path breaks when the new fields
are absent.

#### Stage 0 (current baseline)

- `scope` exists in retrieval as `ASK_DOMAIN_SCOPE` / `domain` (string, not yet named `scope` in
  code). `sphere_memberships` is an additive relation-store seam only. `situated_identity` does
  not exist as a runtime field.
- No behavior change required; SSI-01 through SSI-04 are specification work only.

#### Stage 1 — Rename and alias `scope` at entry points

- Introduce `scope` as the canonical name at ASK entry (`_resolve_domain_scope()` result) and
  orchestrator plan context (`plan.context["scope"]`).
- Backward-compatible: existing `domain` values map directly to `scope` via the SSI-01 rule.
- **Must not break:** any code reading `domain` or `ASK_DOMAIN_SCOPE` directly continues to
  work; the alias is additive.

#### Stage 2 — Add `sphere_memberships` at context entry

- Add `sphere_memberships` as an optional field on `plan.context` and on note frontmatter.
- Pass through `StepContext` without enforcement; tools may ignore it.
- Retrieval may optionally weight results using sphere data but must not change default behavior.
- **Must not break:** absence of `sphere_memberships` is a legal state (empty array or omitted).

#### Stage 3 — Add `situated_identity` at context entry

- Add `situated_identity` as a nullable optional field on `plan.context` and note frontmatter.
- Pass through `StepContext` without enforcement; tools may ignore it.
- **Must not break:** `null` is the legal absent state; no code must substitute a scope value
  for a null identity.

#### Stage 4 — Propagate to output surfaces

- Emit `scope` in panel receipts and watcher-triggered outbox events.
- Emit `sphere_memberships` and `situated_identity` in receipts when present.
- Format defined by SSI-03.

#### Stage 5 — Orientation surface

- Orientation snapshots include context dimension fields when present in the underlying state.
- Format defined by SSI-03.

**Compatibility invariant:** at every stage, a missing or null SSI field must produce the same
runtime behavior as the current baseline. The additive rollout must not require all callers to
be updated before any callers can use the new fields.
