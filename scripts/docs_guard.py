import json
import os
import subprocess
import sys

base = os.environ.get("GITHUB_BASE_REF", "origin/main")
subprocess.run(["git", "fetch", "origin", "+refs/heads/*:refs/remotes/origin/*"], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
changed = subprocess.check_output(["git", "diff", "--name-only", f"{base}...HEAD"], text=True).strip().splitlines()
changed = [c for c in changed if c]
code_changed = any(c.startswith("app/") for c in changed)
allowed_prefixes = ("docs/", "api/", "events/", "vault/_system/settings/", "vault/settings/")
docs_touched = any(any(c.startswith(prefix) for prefix in allowed_prefixes) for c in changed)
if code_changed and not docs_touched:
    print("Docs guard: app/** changed but no docs/contracts/settings updated.")
    print(json.dumps({"changed": changed}, indent=2))
    sys.exit(1)

temporal_docs = {
    "docs/STATUS.md",
    "docs/ROADMAP.md",
    "docs/ARCHITECTURE.md",
    "docs/OPERATIONS.md",
    "docs/HUMAN-FLOWS.md",
    "docs/AGENT-FLOWS.md",
}
temporal_doc_touched = any(c in temporal_docs for c in changed)
temporal_code_prefixes = (
    "app/",
    "scripts/",
    "config/",
    "docs/settings/",
)
temporal_code_changed = any(c.startswith(prefix) for prefix in temporal_code_prefixes for c in changed)
skip_temporal_guard = os.environ.get("DOCS_GUARD_ALLOW_TEMPORAL_SKIP") == "1"

if temporal_code_changed and not temporal_doc_touched and not skip_temporal_guard:
    print("Docs guard: temporal code/config changed but no high-risk temporal docs were touched.")
    print(
        json.dumps(
            {
                "changed": changed,
                "expected_one_of": sorted(temporal_docs),
                "override_env": "DOCS_GUARD_ALLOW_TEMPORAL_SKIP=1",
            },
            indent=2,
        )
    )
    sys.exit(1)
print("Docs guard: OK")
