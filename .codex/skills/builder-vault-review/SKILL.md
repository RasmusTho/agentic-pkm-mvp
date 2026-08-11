---
name: builder-vault-review
description: "Review shared BuilderOps deliberation health and disposition stale, unanswered, duplicated, promotion-pending, conflicted, and orphaned threads without treating projections as authority."
---

# Builder Vault Review

Use this Builder System skill for periodic or threshold-triggered health review of asynchronous
deliberations. Read `_shared/BUILDER_VAULT_DELIBERATION_CONTRACT.md` completely first. Use
`builder-vault-deliberation` for every entry mutation; this skill does not define a second writer.

## Trigger

Run when the owner asks, once per week when a scheduled BuilderOps health pass exists, when the
configured open-thread threshold is reached, or immediately when discovery finds a conflicted or
orphaned thread. If no threshold is configured, report the current counts without inventing one.

This is a cold-path health review. It is not a delivery, merge, closure, or promotion gate.

## Intake

1. Run the shared root/confinement gate.
2. Enumerate and validate every entry; rebuild current content-addressed manifests from entries.
3. Treat any saved projection only as an acceleration hint and compare it with the entry-derived
   set before use.
4. Read current external authority only for threads that cite an Issue, PR, commit, design handoff,
   BuilderOps record/receipt, or promotion target whose live state affects disposition.

## Health Classes

- `unanswered`: a valid open thread has no valid reply.
- `stale`: the configured inactivity threshold has elapsed while the thread remains open,
  answered, or needs review.
- `duplicated`: two threads materially overlap in normalized subject and source refs. Similar text
  alone is evidence for review, not permission to merge or archive.
- `promotion_pending`: a resolution cites a real `PromotionIntent` or other promotion workflow whose
  live owning state is still non-terminal. The deliberation never owns that status.
- `orphaned`: no single valid open entry exists, or a target/hash/manifest edge is missing.
- `conflicted`: duplicate IDs, differing immutable bytes, incomparable corrections/dispositions, or
  an iCloud conflict artifact exists.
- `changed_after_resolution`: valid non-archive activity after the latest resolution invalidates its
  basis. A valid archive that cites the current resolution and manifest remains `archived`.
- `healthy`: none of the above applies.

## Disposition

For each non-healthy thread choose exactly one next action:

- keep open with a named respondent/next check in a new reply;
- correct through a hash-bound correction entry;
- resolve with no authority crossing;
- invoke the existing owner decision, design, Issue, learning, PromotionIntent, PR, or receipt path,
  then cite the resulting artifact in a new resolution;
- archive an already resolved thread;
- preserve and escalate a conflict/orphan without mutation.

Never auto-merge duplicate threads, infer owner approval from silence, mark a promotion complete
from deliberation prose, or archive an unresolved authority question. Agent-owned reversible
dispositions may proceed when evidence is unambiguous. A genuine owner authority decision routes
through `owner-decision-brief`.

## Projection

After validation, optionally write one immutable review projection under
`deliberations/projections/<projection_id>.md`. Label it generated and non-authoritative. Include
the manifest hashes, review timestamp, thresholds supplied by the caller, counts by health class,
thread IDs/subjects, external refs, selected disposition, and conflicts. Exclude entry bodies,
absolute roots, private paths, code, and secrets.

Projection absence or age never changes a thread state. A later review rebuilds from entries and
live external authority; it does not edit the old projection.

## Output

Lead with counts and required actions. Then list only non-healthy threads:

- Thread ID and subject
- Health class
- Last validated activity
- Matching source refs
- Live external authority state, when checked
- Disposition taken or next action
- Conflict/refusal class

End with review projection ID/hash if one was created, or `none`. Never print the absolute vault
root or entry bodies.
