"""Apply the legacy compatibility bootstrap SQL. NOT the migration authority.

`scripts/run_migrations.sh` (`alembic upgrade head`) is the single migration
authority for every container stack and for bare-metal API starts. This script
only replays `app/db/migrations_obsidian.sql`, which since MVR-05A0 (#4543)
contains **no** `file_state` and no `objects.path` DDL — Alembic revision
`c7f4b1a83d29` owns both. Running this alone therefore produces a database a
vault-sync producer will refuse to start against
(`app/db/db.py::assert_file_state_schema`). It has no production caller and is
kept only for the schema-parity tests that assert the legacy runner cannot
create or mutate migration-owned tables.
"""

import os
import psycopg

SQL_PATH = "app/db/migrations_obsidian.sql"


def main() -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    with psycopg.connect(database_url, autocommit=True) as conn, conn.cursor() as cur:
        with open(SQL_PATH, "r", encoding="utf-8") as handle:
            statements = [stmt.strip() for stmt in handle.read().split(";") if stmt.strip()]
        for stmt in statements:
            cur.execute(stmt)
    print("migration applied")


if __name__ == "__main__":
    main()
