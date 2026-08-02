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
when **both** the vault-note identity is absent (no `uuid:` frontmatter on
either side) **and** the two sides' bodies actually diverge. In that case it
returns `status=conflict`, which the driver (`app/cli/merge_driver.py`) turns
into a non-zero exit code — git then raises a normal conflict on that path
instead of silently discarding one side's committed content.

This backstop does not change behavior for any input that carries `uuid:`
frontmatter on either side; the vault-note near-duplicate/"prefer concise"
path is unchanged.

## History

Filed and fixed under GitHub issue #4505: three incidents in one delivery
session had `semanticmd` silently drop committed `docs/**` edits during
routine rebases (exit 0, `MERGE_STATUS=resolved`), including one case where
the discarded content was a correction that got reverted back to the
incorrect prose. See `tests/agents/test_merge_resolver_repo_docs.py` for the
regression coverage.

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
