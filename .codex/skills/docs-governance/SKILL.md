---
name: docs-governance
description: "Decision and routing skill for docs-as-code ownership, anti-sprawl, DOCS_INDEX impact, and narrower docs workflow selection."
---

# Docs Governance

Use this skill before creating or updating docs, extracting docs into issues, reviewing docs drift,
deciding owner-doc impact, adding docs to `docs/DOCS_INDEX.md`, or classifying a doc, spec,
requirement, audit, or proposal.

This is a decision/routing skill. It does not replace `docs-authoring`, `docs-to-issue`,
`feature-breakdown`, `temporal-doc-governance`, or `post-merge-owner-doc`.

## Non-goals

- Do not create a metadata schema.
- Do not add a `system_level` field.
- Do not invent semantic level names.
- Do not invent systems, subsystems, owners, or product boundaries.
- Do not rewrite the SBS or use target-state SBS wording as shipped runtime truth.
- Do not bulk-edit frontmatter.
- Do not add CI enforcement.
- Do not change product/runtime behavior.

## First context to load

- `AGENTS.md`
- `.codex/skills/README.md`
- `docs/DOCS_INDEX.md`
- `docs/architecture/SBS_OPERATING_MODEL.md`
- `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md` when Product/Runtime ownership or interface
  ownership is relevant
- The most local current-state owner doc, spec directory, proposal, or audit named by the request
- The narrower skill selected by the decision below

## Procedure

1. Classify the artifact role.
2. Derive the owner from existing authority only.
3. Decide the docs action using the anti-sprawl rules.
4. Preserve traceability from source docs, source anchors, acceptance criteria, and `Verify:` targets.
5. Apply interface-ownership rules when the artifact describes a boundary.
6. Route to exactly one narrower skill, or produce a no-change receipt.
7. Output a short Docs Governance Decision receipt.

## Artifact roles

- current-state owner doc: claims shipped or currently supported truth.
- target-state/spec: describes intended or required future behavior and must not read as shipped truth.
- proposal: suggests a design, policy, or shape before acceptance.
- historical: retained context that is not active authority.
- reference: implementation, operational, or explanatory detail subordinate to owner docs.
- governance: builder workflow, repo policy, issue/PR rules, skills, or process authority.
- owner doc: the durable surface responsible for a claim, contract, or current-state truth.
- audit snapshot: point-in-time evidence and findings, advisory unless promoted through an owner doc
  or bounded issue.

## Anti-sprawl decision rules

Update an existing doc when:

- the claim belongs to an existing owner doc;
- shipped/current truth is being corrected;
- the material is a subsection of an existing spec or capability directory;
- a roadmap or plan item changed status and owner docs need truth promotion.

Update `docs/DOCS_INDEX.md` when:

- a new stable doc is created;
- a doc role, authority, reading order, or owner changes;
- a doc is archived, demoted, or promoted;
- canonical entrypoints or reading paths change;
- a representative row is needed for a new spec directory or audit snapshot.

Create a new doc only when all of these hold:

- no existing owner doc can hold the responsibility cleanly;
- the doc has a durable role and owner;
- the doc has a distinct audience or authority boundary;
- the doc will be indexed or intentionally covered by a directory row;
- the doc avoids duplicating owner-doc content.

Create a follow-up issue when:

- wording needs judgment;
- doc repair is too large for the current change;
- traceability or `Verify:` evidence is missing and executable work is needed;
- a stale or duplicate area needs bounded cleanup.

Produce a no-change receipt when:

- the source is historical or snapshot-only;
- the change affects no shipped truth or contract;
- live evidence belongs in a parent issue or BuilderOps record;
- a directory README already indexes sibling specs sufficiently.

## SBS-derived ownership

Use only existing SBS and Builder System elements. Ownership order:

1. explicit owner in `docs/DOCS_INDEX.md` or the doc header;
2. `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md`;
3. boundary register or contract owner;
4. path convention;
5. nearest parent in SBS or existing owner doc if unclear.

Never infer a new subsystem from a file path, feature name, external tool, product name, or agent
name. For Builder System work, use the Builder System boundary and artifact map in
`docs/architecture/SBS_OPERATING_MODEL.md`; do not recast repo-local skills as Product/Runtime
CAO/MEM capabilities.

## Interface ownership

- Internal/internal interfaces are owned by the nearest common parent.
- Yggdrasil external interfaces are owned by Yggdrasil.
- Internal/external interfaces are owned by the internal system.
- External systems are not above Yggdrasil.
- Client-facing contracts must exist as committed artifacts if issues or specs depend on them.

If the interface owner cannot be assigned without inventing a system, use a Human Exception.

## Routing

- Use `docs-authoring` when the action is to update or create authoritative docs, including
  `docs/DOCS_INDEX.md`, without product/runtime implementation.
- Use `docs-to-issue` when active docs should become one bounded executable GitHub Issue with source
  anchors and `Verify:` targets.
- Use `feature-breakdown` when one docs item is too large for one issue, needs a specification
  directory, or needs post-merge validation before owner-doc promotion.
- Use `temporal-doc-governance` when the problem is temporal drift in current-state, status, roadmap,
  rollout, freshness, or snapshot posture.
- Use `post-merge-owner-doc` after a merged PR to decide whether owner docs need an immediate PR, a
  follow-up issue, or a no-change receipt.

Do not route to multiple narrower skills unless the first skill explicitly hands off to the next one.

## Output format

Use this exact receipt shape:

```text
Docs Governance Decision:
- Artifact role:
- Owner:
- Action:
- Traceability:
- DOCS_INDEX impact:
- SBS/interface ownership:
- Next skill or no-change receipt:
- Human Exception:
```

Set `Human Exception` to `none` unless one of the conditions below applies.

## Human Exception conditions

Use a Human Exception only when:

- the owner cannot be derived from existing SBS, path, or parent authority;
- source authority conflicts and the current-state owner doc cannot resolve it;
- interface ownership cannot be assigned without inventing a system;
- the requested doc would create new policy authority outside established owner docs;
- the user asks to encode future target state as shipped truth.

The exception should name the missing authority, the choices the human must make, and the smallest
safe no-change or follow-up posture until the decision exists.

## Capturing learning

On a plan divergence, route it through `capture-learning`; that skill owns invocation timing and the
"name an upstream artifact or do not log" gate.
