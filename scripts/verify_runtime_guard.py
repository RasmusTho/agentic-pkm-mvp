from __future__ import annotations

import re
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    offenders: list[str] = []

    yaml_paths: list[Path] = []
    yaml_paths.extend(repo.glob("docker-compose*.y*ml"))
    configs_dir = repo / "configs"
    if configs_dir.exists():
        yaml_paths.extend(configs_dir.rglob("*.y*ml"))

    # Any literal value for these keys in compose/configs is considered a hardcoded default.
    keys = ("VAULT_INBOX_DIR_REL", "WATCHER_SCOPE_GLOB")

    for path in sorted(set(yaml_paths)):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue

        for ln, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            for key in keys:
                m = re.match(rf"\s*{re.escape(key)}\s*:\s*(.*)", line)
                if not m:
                    continue

                val = m.group(1).strip()
                if not val:
                    continue

                # Allowed: pass-through from env.
                if val.startswith("${"):
                    continue

                offenders.append(
                    f"{path.relative_to(repo)}:{ln}: {key} has literal value: {val}"
                )

    # Guard against env defaults in Python code for vault-layout-derived keys.
    py_roots = [repo / "app", repo / "scripts", repo / "configs"]
    py_paths: list[Path] = []
    for r in py_roots:
        if r.exists():
            py_paths.extend(r.rglob("*.py"))

    default_env_patterns = [
        re.compile(r"\bos\.getenv\(\s*['\"]VAULT_INBOX_DIR_REL['\"]\s*,\s*['\"]"),
        re.compile(r"\bos\.environ\.get\(\s*['\"]VAULT_INBOX_DIR_REL['\"]\s*,\s*['\"]"),
        re.compile(r"\bos\.getenv\(\s*['\"]WATCHER_SCOPE_GLOB['\"]\s*,\s*['\"]"),
        re.compile(r"\bos\.environ\.get\(\s*['\"]WATCHER_SCOPE_GLOB['\"]\s*,\s*['\"]"),
    ]

    for path in py_paths:
        rel = path.relative_to(repo)
        # This guard script itself is allowed to contain the patterns.
        if rel == Path("scripts/verify_runtime_guard.py"):
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue

        for pat in default_env_patterns:
            if pat.search(text):
                offenders.append(
                    f"{rel}: uses an env default for a vault-layout-derived key"
                )
                break

    if offenders:
        print("Hardcoded vault-layout defaults found:")
        for o in offenders:
            print(o)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
