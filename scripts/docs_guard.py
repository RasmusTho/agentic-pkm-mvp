import argparse
import json
import os
import subprocess
import sys

from docs_guard_logic import (
    TEMPORAL_DOCS,
    non_english_documentation,
    requires_temporal_owner_doc,
)


parser = argparse.ArgumentParser(description="Validate repository documentation guardrails.")
parser.add_argument(
    "--language-only",
    action="store_true",
    help="Run only the full-repository English documentation policy.",
)
args = parser.parse_args()

tracked_docs_raw = subprocess.check_output(
    ["git", "ls-files", "-z", "--", "*.md", "*.mdx", "*.rst"]
)
tracked_docs = [
    path.decode("utf-8") for path in tracked_docs_raw.split(b"\0") if path
]
language_violations = non_english_documentation(tracked_docs)
if language_violations:
    print("Docs language guard: repository documentation must use English as primary prose.")
    print(
        json.dumps(
            {
                "violations": language_violations,
                "scope": "governed repository documentation; product/vault/test corpus excluded",
                "allowed": "bounded non-English examples inside otherwise-English documentation",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    sys.exit(1)
if args.language_only:
    print("Docs language guard: OK")
    sys.exit(0)

def _resolves(ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


# GitHub Actions always defines GITHUB_BASE_REF and sets it to the empty string
# on non-pull_request events. Reading it with a `.get` default therefore yielded
# "" there, and `git diff ...HEAD` treats an empty left side as HEAD — so the
# guard silently diffed HEAD against itself and passed on an empty changeset.
# `or` restores the intended origin/main fallback.
base = os.environ.get("GITHUB_BASE_REF") or "origin/main"
subprocess.run(["git", "fetch", "origin", "+refs/heads/*:refs/remotes/origin/*"], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
# On pull_request events GITHUB_BASE_REF is a bare branch name ("main"), and
# actions/checkout leaves no local branch by that name, so the three-dot diff
# below could not resolve a merge base. Prefer the remote-tracking ref the fetch
# above just populated. An already-resolvable base (an explicit "origin/main",
# or a revision such as "HEAD~1") is used as-is.
if not _resolves(base) and _resolves(f"origin/{base}"):
    base = f"origin/{base}"
changed = subprocess.check_output(["git", "diff", "--name-only", f"{base}...HEAD"], text=True).strip().splitlines()
changed = [c for c in changed if c]
code_changed = any(c.startswith("app/") for c in changed)
allowed_prefixes = ("docs/", "api/", "events/", "vault/settings/")
docs_touched = any(any(c.startswith(prefix) for prefix in allowed_prefixes) for c in changed)
if code_changed and not docs_touched:
    print("Docs guard: app/** changed but no docs/contracts/settings updated.")
    print(json.dumps({"changed": changed}, indent=2))
    sys.exit(1)

skip_temporal_guard = os.environ.get("DOCS_GUARD_ALLOW_TEMPORAL_SKIP") == "1"

if requires_temporal_owner_doc(changed) and not skip_temporal_guard:
    print("Docs guard: temporal code/config changed but no high-risk temporal docs were touched.")
    print(
        json.dumps(
            {
                "changed": changed,
                "expected_one_of": sorted(TEMPORAL_DOCS),
                "override_env": "DOCS_GUARD_ALLOW_TEMPORAL_SKIP=1",
            },
            indent=2,
        )
    )
    sys.exit(1)
print("Docs guard: OK")
