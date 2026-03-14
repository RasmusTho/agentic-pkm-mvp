State: <state summary>
Doc role: Core SoT | Reference | Plan | Historical
Authority: <what this document is authoritative for, and what it does not override>
Last reviewed: YYYY-MM-DD

# <Document Title>

## Purpose

State why this document exists and what decision or implementation surface it supports.

## Scope

- What this document covers
- What level of detail it is intended to hold
- Which audience it is written for

## Out of Scope

- What this document does not define
- Which neighboring docs should be used instead

## Related Docs

- `docs/...` — neighboring authoritative or supporting documents
- `docs/...` — historical or planned docs when relevant

## Normative Content

Put the actual contract, behavior, model, workflow, or reference material here.

Recommended patterns:
- use flat lists for invariants, rules, and responsibilities
- use tables for stable taxonomies, ownership maps, compatibility matrices, or settings surfaces
- use examples only where ambiguity would otherwise remain

## Change Notes

Optional. Use when the document needs a short note about recent scope shifts, migrations, or compatibility concerns.

## Writing Guidance

- Keep one document focused on one responsibility.
- Do not restate large sections from neighboring docs; link instead.
- If the document is `Core SoT`, write normatively and resolve ambiguity explicitly.
- If the document is `Reference`, explain implementation or operational detail without pretending to define system truth.
- If the document is `Plan`, separate current reality from future intent.
- If the document is `Historical`, make it explicit that it is not current truth.
