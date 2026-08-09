---
name: builder-vault-deliberation
description: "Create, discover, read, search, reply to, correct, resolve, and archive attributed asynchronous deliberation threads in the shared BuilderOps artifact vault without creating delivery authority."
---

# Builder Vault Deliberation

Use this Builder System skill when an agent or owner needs asynchronous, attributed discussion that
must survive chat/session boundaries but is not yet an Issue, decision, promotion, or repo change.

Read `_shared/BUILDER_VAULT_DELIBERATION_CONTRACT.md` completely before any live vault operation. It
owns the root gate, immutable entry format, hash/manifest rules, content exclusions, derived states,
and promotion boundary. This skill owns only the user-facing operations below.

## When To Use

- Ask another Codex, Claude Code, automation, or the owner a builder-workflow question asynchronously.
- Discover whether current Issue/PR/docs/design work already has an open deliberation.
- Add a reply or a hash-bound correction without editing earlier content.
- Record a non-authoritative resolution or archive a resolved thread from default discovery.

Do not use it for runtime/user knowledge, product code review, executable backlog, claim/lease state,
approval, merge/closure state, or a decision that an existing owner workflow already owns.

## Read And Search

1. Run the shared root/confinement gate.
2. Enumerate thread entry files under `deliberations/threads/`; do not trust a projection as the only
   source.
3. Validate body hashes, whole-file hashes, targets, corrections, and the current content-addressed
   manifest before reporting a thread state.
4. Search by explicit source refs first: Issue/PR number, commit SHA, BuilderOps ID, repo-relative
   `file:line`, then normalized subject words. Never search or display absolute host paths.
5. Re-read GitHub, repo, BuilderOps, design, or receipt authority live when the answer depends on
   current external state.

Return concise matches. A missing, stale, or invalid manifest is a rebuild requirement, not evidence
that the thread is empty or resolved.

## Create

1. Confirm that losing the material would cost enough to justify a durable thread and that an
   existing Issue/comment/decision/design workflow is not the better owner.
2. Choose fresh collision-resistant thread and entry IDs. Supply explicit actor and client identity.
3. Write one `open` entry with a bounded subject, question/context, and authority-safe source refs.
   Keep code, diffs, secrets, private paths, and personal vault content out.
4. Install the entry through the shared immutable write protocol, verify it, then create the matching
   content-addressed manifest from the validated set.
5. Report the thread ID, vault-relative thread location, entry hash, and current derived state. Do
   not report the absolute root.

## Reply

1. Read and validate the full current thread.
2. Name the exact entry ID and whole-file hash being answered.
3. Append a new immutable `reply` entry. A reply may disagree; it must not rewrite the target or
   claim that disagreement changed external authority.
4. Rebuild the content-addressed manifest and report any concurrent activity discovered during
   readback.

## Correct

Corrections are additive. Append `correction` with the exact target ID/hash and a clear explanation.
Never edit or delete the original. If another incomparable correction already targets the same
entry, stop with a conflict; a later reconciliatory correction must cite both rather than silently
choosing one.

## Resolve

1. Validate all entries and build the complete current manifest.
2. Decide whether the outcome is only deliberation disposition or must cross an existing authority
   boundary. Invoke the owning skill named in the shared contract for any crossing.
3. Append `resolution` citing the manifest hash and only external targets that already exist.
4. Re-read the entry set. Any post-basis activity changes the derived state to `needs_review`; do not
   claim resolution until a new disposition considers it.

## Archive

Archive only a valid current resolution. Append `archive` citing the resolution entry/hash and the
current manifest. Do not move the directory, delete entries/manifests, or create a mutable archive
index. Archived threads remain discoverable with an explicit include-archived search.

## Session-Close Hook

Before closing a substantial analysis or builder session, search for threads matching its Issue,
PR, commit, docs, design, or BuilderOps refs. If the session leaves a meaningful unanswered question,
reply or create one bounded thread. If all durable meaning already lives in an authoritative surface,
record no deliberation and say `none` in the session handoff. This hook does not turn every chat into
a vault note.

## Failure Output

On refusal, report the thread ID or vault-relative target, exact failure class, and safe next action:
root invalid, fixture selected, conflict artifact, missing hash, target mismatch, unsafe content,
external authority unavailable, or ambiguous write outcome. Never print the absolute vault root,
unsafe content, or a credential-shaped value.

## Output

- Operation: create | read | search | reply | correct | resolve | archive
- Thread and entry IDs
- Derived state
- Source refs
- Manifest and artifact hashes
- External authority action: none or owning workflow/result
- Conflict/refusal: none or exact safe class
