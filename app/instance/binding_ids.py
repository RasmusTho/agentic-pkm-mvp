"""Binding identifiers shared across storage-neutral runtime seams."""

# MVR-05A0 (#4543) / MVR-05A1 (#4560): every row inherited from the
# single-vault runtime is attributed to this explicit transitional namespace.
# Keeping the value outside ``app.db`` lets identity, rebuild, and diagnostic
# code name the namespace without acquiring direct database-layer authority.
COMPATIBILITY_BINDING_ID = "legacy-compatibility-binding"
