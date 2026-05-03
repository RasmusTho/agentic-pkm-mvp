from app.context_dimensions import ContextDimensions, from_legacy_domain


def test_context_dimensions_schema() -> None:
    payload = ContextDimensions(scope="work", sphere_memberships=["team"], situated_identity="maker")
    assert payload.scope == "work"
    assert payload.sphere_memberships == ["team"]
    assert payload.situated_identity == "maker"


def test_domain_to_scope_migration() -> None:
    migrated = from_legacy_domain("work")
    assert migrated.scope == "work"
    assert migrated.sphere_memberships == []
    assert migrated.situated_identity is None


def test_context_dimensions_invariants() -> None:
    defaulted_scope = ContextDimensions(scope=None, sphere_memberships=None, situated_identity=None)
    assert defaulted_scope.scope == "default"
    assert defaulted_scope.sphere_memberships == []
    assert defaulted_scope.situated_identity is None


def test_context_dimensions_importable() -> None:
    payload = ContextDimensions(scope="default", sphere_memberships=[], situated_identity=None)
    assert payload.model_dump() == {
        "scope": "default",
        "sphere_memberships": [],
        "situated_identity": None,
    }
