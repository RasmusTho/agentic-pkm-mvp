---
name: Classify Deployed Infrastructure
description: Add an infra classification column/section to docs/ARCHITECTURE.md System Context resolving the Ollama/Postgres/Colima dual-listing contradiction
task_id: SBI-2
source_anchor: "docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md :: §2, §14"
parent_capability: SYSTEM_CONTEXT_OVERLAY
prerequisites: [SBI-1]
depends_on: [define-system-context-overlay.md]
can_parallelize_with: []
---

# Classify Deployed Infrastructure

## Purpose

The same Ollama is described as an "optional external provider" outside the repo boundary
(`docs/ARCHITECTURE.md:109`) and as a first-party compose service with healthcheck and volume
(`docker-compose.yaml:16-31`); the same Postgres is "extension fabric" inside the system
(`docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md:58`), an "external durable store"
(`docs/INTEGRATION_FABRIC_CONTRACT.md:41`), and an unlabeled service
(`docs/INFRASTRUCTURE.md:17`) in three different docs. This task resolves the contradiction with one
classification column/section, using the vocabulary SBI-1 defines.

## What This Task Does

Extend `docs/ARCHITECTURE.md :: System Context (Current)` (line ~95) with one classification
column or subsection — one row per deployed element — using the four-class rule from SBI-1's
overlay doc (SoI component / COTS system element / enabling system / external system). Cover, at
minimum, every service in `docker-compose.yaml` and every host process listed in
`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md:28-67`: db (Postgres/pgvector), Ollama, api, worker,
watcher, companion-ui gateways, Colima, Tailscale, GitHub, iCloud.

For Ollama specifically: classify **both** bindings — COTS system element when run as the compose
service (`docker-compose.yaml:16-31`), external system when reached as a host/remote service
(`docs/ARCHITECTURE.md:109`) — and state explicitly that the classification attaches to the
*deployment binding*, not the product name.

Reference, do not duplicate: the classification section points at
`docs/architecture/SBS_BOUNDARY_REGISTER.md` and `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`
for module/host detail rather than re-listing it. The register itself disclaims allocation readings
(`SBS_BOUNDARY_REGISTER.md:16-17`) — this section is explicitly non-SBS-owned, a current-reality
infrastructure classification, not a boundary allocation.

**Sequencing check before starting:** confirm deployment epic #2655 S5/S7 has landed (or explicitly
re-verify against the current pinned-image topology if it has not) — #2655 is about to replace the
deployment units this task would cite. Also confirm the state of #2825 (same
`docs/ARCHITECTURE.md :: System Context` region) before editing — diff against its landed change if
it merged first, or coordinate to avoid a double-edit collision (see `README.md :: Cross-Task
Invariants`, item 2).

## Concretely

```bash
grep -n "^## System Context" docs/ARCHITECTURE.md
docker compose -f docker-compose.yaml config --services   # enumerate services to classify
grep -n "^| " docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md | sed -n '28,67p'  # host processes
grep -c "SoI component\|COTS system element\|Enabling system\|External system" docs/ARCHITECTURE.md
```

## Why This Matters

Without a single classification section, every doc that mentions Ollama or Postgres keeps
re-deriving its own answer to "is this inside or outside the system," and the answers keep
disagreeing — exactly the pattern the audit's executive summary names as the top systemic finding
(blast radius × silence of failure). A classification gap is invisible until someone builds an
integration or a security review on the wrong assumption.

## Acceptance Criteria

- [ ] `docs/ARCHITECTURE.md :: System Context (Current)` contains a classification
      column/section covering every `docker-compose.yaml` service and every host process from
      `DEPLOYMENT_AND_ENVIRONMENTS.md:28-67`, each with exactly one of the four classes.
      Verify: doc writeback at `docs/ARCHITECTURE.md :: System Context (Current)` — row count
      matches `docker compose config --services` count plus the host-process list
- [ ] Ollama's two bindings (compose service, host/remote service) are both classified, with the
      binding-not-product-name rule stated in one sentence.
      Verify: doc writeback at `docs/ARCHITECTURE.md :: System Context (Current)` — two distinct
      Ollama rows/entries present
- [ ] The section references (not duplicates) `SBS_BOUNDARY_REGISTER.md` and
      `DEPLOYMENT_AND_ENVIRONMENTS.md`, and states it is non-SBS-owned.
      Verify: doc writeback at `docs/ARCHITECTURE.md :: System Context (Current)` — contains a
      cross-reference sentence to both docs and an explicit non-SBS-owned disclaimer
- [ ] No conflict with a concurrently-landed #2825 edit to the same section.
      Verify: `git log --oneline -- docs/ARCHITECTURE.md` shows this task's commit rebased onto (not
      silently overwriting) any #2825 commit to the same region

## How to Verify (Pre-Merge)

1. `grep -n "SoI component\|COTS system element\|Enabling system\|External system" docs/ARCHITECTURE.md`
   — confirm every deployed element has exactly one class.
2. Cross-check against `docker compose -f docker-compose.yaml config --services` and
   `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md:28-67` for completeness (no element missing).
3. Confirm #2655 S5/S7 status and #2825 status before merge; if either changed the same doc region
   concurrently, rebase and reconcile rather than overwrite.
4. `grep -n "docs/architecture/SBS_BOUNDARY_REGISTER.md\|docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md" docs/ARCHITECTURE.md`
   — confirm the reference (not duplication) pattern.

## Out of Scope

- Creating a new allocation table (the audit explicitly recommends against this — "not a new
  allocation table," audit §2).
- Any change to `SBS_BOUNDARY_REGISTER.md` module anchors (SBI-4's scope).
- The dual-role hazard (infrastructure as both enabling system and domain-of-interest) — named in
  the audit, deferred to the companion thread; this task classifies lifecycle role only, not the
  hazard stance.
- Changing `docker-compose.yaml` or any runtime deployment topology — this task only classifies the
  existing topology in docs.

## Related Docs

- `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md :: §2`
- `docs/ARCHITECTURE.md :: System Context (Current)` (line ~95)
- `docs/architecture/SBS_BOUNDARY_REGISTER.md`, `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`
  (lines 28-67, 146-156), `docker-compose.yaml`
- Sibling issue #2825 (same doc region); deployment epic #2655 (S5/S7 sequencing)

## Related GitHub Issues

One bounded issue. TCD hint: Sonnet / medium effort — mechanical classification against an
already-defined four-class rule, with one coordination check (#2655/#2825 sequencing) before
starting. Escalate to high effort only if #2655's topology change is mid-flight and the
classification target is genuinely ambiguous.
