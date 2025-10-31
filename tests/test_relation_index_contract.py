from datetime import datetime, timezone
from app.store.relation_index import RelationIndex, RelationEdge, GraphSlice

def test_relation_index_interface_shape():
    ri = RelationIndex
    assert hasattr(ri, "link")
    assert hasattr(ri, "neighborhood")

    now = datetime.now(timezone.utc)

    e = RelationEdge(
        src_uuid="a",
        dst_uuid="b",
        relation_type="supports",
        weight=1.0,
        provenance={"who": "test"},
        created_at=now,
    )
    assert e.src_uuid == "a"
    assert e.dst_uuid == "b"
    assert e.relation_type == "supports"
    assert e.weight == 1.0
    assert e.provenance["who"] == "test"
    assert e.created_at == now

    g = GraphSlice(center="a", edges=[e])
    assert g.center == "a"
    assert g.edges[0].src_uuid == "a"
