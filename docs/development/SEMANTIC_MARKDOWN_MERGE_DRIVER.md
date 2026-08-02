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

## Known follow-up (not fixed by #4505)

`app/cli/merge_driver.py` only prints its computed merge result to stdout; it
never writes the result into the git-provided `%A` path, which the custom
merge driver contract in `git help gitattributes` requires for a driver to
actually land its computed content in the working tree on a successful
(`resolved`, exit 0) merge. A real `git rebase` repro shows the "resolved"
path currently leaves whatever content was already at `%A` untouched — a
correctness gap for the vault-note path as well, tracked separately (not part
of #4505's bounded scope, which only requires that this driver never claim
success while silently discarding content — the `conflict`/non-zero path
above already forces git to stop and surface a real conflict regardless of
this gap).
