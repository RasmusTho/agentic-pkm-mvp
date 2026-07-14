import json
import os
import subprocess
import sys

from docs_guard_logic import TEMPORAL_DOCS, requires_temporal_owner_doc

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
