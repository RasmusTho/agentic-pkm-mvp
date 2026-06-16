"""Fitness guard: remediated test modules must not mutate ``os.environ`` directly.

Direct ``os.environ`` mutation in a test leaks process-env state across the whole
pytest session (the mutation is never torn down), which contaminates later tests
-- especially subprocess-spawning ones that inherit ``os.environ``. That is the
upstream cause class behind #2066 (an order-dependent env leak) and the defensive
patch in #2091.

Tests must set process env only via pytest's ``monkeypatch`` fixture (function
scoped, auto-restored) or the autouse fixtures in ``tests/conftest.py``
(``force_memory_store_for_non_pg`` / ``default_pg_dsn_for_pg_tests`` /
``default_vault_layout_env``). This guard pins the files remediated under #2101 so
they cannot regress to raw mutation.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Files remediated for direct os.environ mutation under #2101. Reads
# (os.environ.get / .copy / subscript comparison) stay allowed; only mutation is
# forbidden.
GUARDED_TEST_FILES = (
    "tests/agents/test_projector.py",
    "tests/agents/test_reviewer.py",
    "tests/agents/test_set_evaluator.py",
    "tests/agents/test_citation_checker.py",
    "tests/agents/test_memory.py",
    "tests/jobs/test_backfill.py",
    "tests/dispatcher/test_bootstrap.py",
    "tests/dispatcher/test_cli.py",
)

# Matches os.environ["X"] = ... (single '=', not '=='), the mutating method calls,
# and ``del os.environ``. Does not match reads such as os.environ.get(...),
# os.environ.copy(), or os.environ["X"] == "y".
_RAW_ENV_MUTATION = re.compile(
    r"""os\.environ\s*\[[^\]]*\]\s*=(?!=)"""  # subscript assignment
    r"""|os\.environ\.(?:setdefault|update|pop|popitem|clear|setitem)\("""  # mutators
    r"""|\bdel\s+os\.environ\b"""  # del os.environ / del os.environ["X"]
)


def test_guarded_test_files_have_no_raw_environ_mutation() -> None:
    offenders: list[str] = []
    for rel in GUARDED_TEST_FILES:
        path = REPO_ROOT / rel
        assert path.exists(), f"guarded file missing: {rel}"
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _RAW_ENV_MUTATION.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

    assert not offenders, (
        "Raw os.environ mutation found in guarded test files; use "
        "monkeypatch.setenv/delenv or an autouse conftest fixture instead:\n"
        + "\n".join(offenders)
    )
