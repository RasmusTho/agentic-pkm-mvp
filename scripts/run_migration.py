import os
import psycopg

SQL_PATH = "app/db/migrations_obsidian.sql"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:15432/app")


def main() -> None:
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        with open(SQL_PATH, "r", encoding="utf-8") as handle:
            statements = [stmt.strip() for stmt in handle.read().split(";") if stmt.strip()]
        for stmt in statements:
            cur.execute(stmt)
    print("migration applied")


if __name__ == "__main__":
    main()
