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
