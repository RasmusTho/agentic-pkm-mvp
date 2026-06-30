from __future__ import annotations

import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_fake_pg_dump(bin_dir: Path, marker_path: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "pg_dump"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            : > "{marker_path}"
            echo "pg_dump should not be invoked for prod-looking DSNs" >&2
            exit 98
            """
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def test_db_snapshot_refuses_prod_dsn_or_never_emits_dev_prefixed_dump(
    tmp_path: Path,
) -> None:
    snapshot_dir = tmp_path / ".db-snapshots"
    fake_bin = tmp_path / "bin"
    marker_path = tmp_path / "pg_dump-invoked"
    _write_fake_pg_dump(fake_bin, marker_path)

    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": "postgresql+psycopg://app:app@127.0.0.1:15432/app",
            "DB_DSN": "",
            "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
            "PYTHON": sys.executable,
            "SNAPSHOT_DIR": str(snapshot_dir),
        }
    )

    result = subprocess.run(
        ["make", "-s", "db-snapshot"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    combined = result.stdout + result.stderr

    assert result.returncode != 0, combined
    assert "REFUSING: db-snapshot target DSN looks like prod" in combined, combined
    assert not marker_path.exists(), "pg_dump was invoked despite the prod guard"
    assert not list(snapshot_dir.glob("dev_*.dump")), (
        "db-snapshot must not emit a dev_-prefixed dump for a prod-looking DSN"
    )
    assert not list(snapshot_dir.glob("prod_*.dump")), (
        "db-snapshot should refuse instead of relabeling to a prod_-prefixed dump"
    )
