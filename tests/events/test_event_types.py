from app.events import types


def test_ingest_object_deleted_event_type_is_exported() -> None:
    assert types.INGEST_OBJECT_DELETED == "ingest.object.deleted"
    assert "INGEST_OBJECT_DELETED" in types.__all__
