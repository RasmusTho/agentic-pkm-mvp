from app.db import conn_rw

def main():
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                select id, kind, payload->>'review_state' as review_state,
                       payload->>'title' as title,
                       payload->>'source_uuid' as source_uuid,
                       created_at
                from objects
                order by created_at desc
                limit 20
            """)
            rows = cur.fetchall()
            for r in rows:
                print("id:", r["id"])
                print(" kind:", r["kind"])
                print(" review_state:", r["review_state"])
                print(" title:", r["title"])
                print(" source_uuid:", r["source_uuid"])
                print(" created_at:", r["created_at"])
                print("---")
if __name__ == "__main__":
    main()
