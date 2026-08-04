State: Current-state contract for the `semanticmd` git merge driver; aligned with shipped behavior (#4505 routing narrowing, #4561 `%A` result write, #4603 content-loss guard generalized to vault notes, #4616 lossless-only link carryover and vault-scoped near-duplicate bypass).

# Semantic Markdown merge driver (`semanticmd`)

Owner: Builder System (git tooling) / Product vault-sync (resolver logic).

## What it is

`app/cli/merge_driver.py` (`merge_note_from_blobs` in
`app/agents/merge_resolver/agent.py`) is a git custom merge driver, wired via
`make setup-merge-driver` into `[merge "semanticmd"]` in local git config and
routed by path in `.gitattributes`. It is a **vault-note** merge agent: it
reads `uuid:` frontmatter as the note's stable identity, carries links across
revisions, and prefers the shorter side when two revisions are near-duplicate
(`sim >= 0.85`) — heuristics designed for Obsidian-style notes synced across
devices under `vault/**`.

## Routing contract

- `vault/**` (and any other markdown that genuinely carries `uuid:`
  frontmatter identity) uses `merge=semanticmd`.
- Code-review-approved repository documentation has no vault-note identity and
  must use git's built-in 3-way text merge instead, so a real divergent edit
  raises an ordinary conflict rather than being silently resolved. This is
  pinned in `.gitattributes` for the highest-traffic paths: `docs/**`,
  `/README.md`, `/AGENTS.md`, `/CLAUDE.md`, `/CONTRIBUTING.md`,
  `/THIRD_PARTY_NOTICES.md`, and `.codex/**`.

## Resolver-level backstop

Path narrowing alone cannot cover every present or future repository doc
outside the pinned paths above (nested `README.md` files, generated docs,
etc.), so `merge_note_from_blobs` itself refuses to report `status=resolved`
when the two sides' bodies actually diverge and no verified-safe resolution
mechanism accounts for the divergence. In that case it returns
`status=conflict`, which the driver (`app/cli/merge_driver.py`) turns into a
non-zero exit code — git then raises a normal conflict on that path instead of
silently discarding one side's committed content.

This guard applies uniformly to every input, including vault notes (`uuid:`
frontmatter present). It was originally scoped to non-vault-note input only,
on the assumption that vault-note merging performs real semantic judgment and
is therefore safe. It does not: `judge_locus`
(`app/agents/merge_resolver/llm.py`) is a stub that returns an LLM prompt pack,
not a resolved decision, so `apply_decisions` always keeps OURS (%A)
regardless of what THEIRS contains and still reports "resolved". Once #4561
made the driver actually write that "resolved" result to `%A`, a real vault
note merge with a genuine two-sided divergence became a clean, silent rebase
that permanently drops one side's edit. See
`tests/cli/test_merge_driver.py::test_end_to_end_git_rebase_plain_prose_vault_note_divergence_is_not_silently_dropped`
for the regression coverage.

Three mechanisms are trusted to resolve a divergence without raising a
conflict, because they provably do not discard real body content (tightened
by #4616 after PR #4604 reviews r3700682703 / r3700682705; frontmatter
divergence beyond the uuid invariant is a pre-existing gap outside this
guard's contract):

- An exact body match: nothing to lose.
- The markdown-link-carryover heuristic (THEIRS' missing links are appended
  into the merged text), but only when the carryover is verifiably lossless:
  every one of THEIRS' links must land in the merged body and THEIRS'
  remaining non-link prose must already appear, word-aligned and in order,
  inside the merged body's non-link prose. If THEIRS carries a link plus
  distinct prose — or an image embed, which carryover cannot preserve — the
  merge conflicts instead of resolving; link carryover is not a generic
  content-loss exemption.
- A genuine near-duplicate pick (token similarity `>= 0.85`), scoped to vault
  notes (a non-empty `uuid:` identity on both sides). Set-of-tokens
  similarity ignores order, repetition, and negation ("deployment is enabled"
  vs "deployment is not enabled" clears the threshold), so repository
  documentation never resolves through it; a non-vault doc with high token
  overlap but distinct body content conflicts.

Any other divergence — including ordinary distinct-prose additions on
both sides — raises a conflict rather than silently picking a side. Real
per-locus semantic merging (an actual LLM judgment wired into `judge_locus`)
is not implemented; until it is, auto-resolve is limited to the
three mechanisms above.

## History

Filed and fixed under GitHub issue #4505: three incidents in one delivery
session had `semanticmd` silently drop committed `docs/**` edits during
routine rebases (exit 0, `MERGE_STATUS=resolved`), including one case where
the discarded content was a correction that got reverted back to the
incorrect prose. See `tests/agents/test_merge_resolver_repo_docs.py` for the
regression coverage.

Filed and fixed under GitHub issue #4603: delivering #4505 surfaced that its
non-vault-only guard scoping rested on a false premise (vault-note merging
"working" as real semantic merge). A real git-driver-level repro proved vault
notes hit the identical silent-drop defect once #4561 made the `%A` write
land. See the "Resolver-level backstop" section above and
`tests/cli/test_merge_driver.py::test_end_to_end_git_rebase_plain_prose_vault_note_divergence_is_not_silently_dropped`.

Filed and fixed under GitHub issue #4616: a post-merge review of PR #4604
(#4603's fix) left two P1 content-loss findings. Link carryover could report
a clean resolve while dropping THEIRS' distinct non-link prose, and the
token-similarity near-duplicate bypass let a non-vault repository doc with
high token overlap (e.g. a flipped negation) resolve to OURS silently. The
backstop now requires verifiably lossless link carryover and scopes the
near-duplicate bypass to vault identity, per the "Resolver-level backstop"
section above. See
`tests/agents/test_merge_resolver_repo_docs.py::test_link_carryover_does_not_hide_incoming_prose_loss`
and `::test_repo_doc_token_overlap_still_conflicts_when_bodies_differ`.

## `%A` file-write contract (fixed by #4496)

`app/cli/merge_driver.py` now writes its computed merge result into the
git-provided `%A` (`a_path`) on a `resolved` (exit 0) outcome, per the custom
merge driver contract in `git help gitattributes`: git reads the merge result
back from `%A`, not from the driver's stdout. Diagnostics
(`MERGE_STATUS=`/`MERGE_REASON=`) go to stderr only and never enter the
merged file content. On a non-`resolved` outcome (`conflict`/`prompted`,
non-zero exit) the driver leaves `%A` untouched so git's normal conflict
handling applies. See `tests/cli/test_merge_driver.py` for the file-contract
regression coverage, including an end-to-end `git merge` through the
configured `semanticmd` driver.
