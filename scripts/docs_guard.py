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
print("Docs guard: OK")
