from __future__ import annotations

from app.outbox import events as outbox_events

def main() -> None:
    path = outbox_events.get_index_outbox_path()
    print(
        "indexer: JSONL queue consumption disabled; use DB outbox worker for "
        f"{outbox_events.INDEX_EMBEDDING_REQUESTED} events (audit log at {path})"
    )


if __name__ == "__main__":
    main()
