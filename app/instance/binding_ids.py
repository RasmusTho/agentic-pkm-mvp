"""Binding identifiers shared across storage-neutral runtime seams."""

# MVR-05A0 (#4543) / MVR-05A1 (#4560): every row inherited from the
# single-vault runtime is attributed to this explicit transitional namespace.
# Keeping the value outside ``app.db`` lets identity, rebuild, and diagnostic
# code name the namespace without acquiring direct database-layer authority.
COMPATIBILITY_BINDING_ID = "legacy-compatibility-binding"

# MVR-05A7 (#4581): fail-safe attribution for an outbox row whose partially
# upgraded shape proves that it is not a plain scalar-era row but carries no
# usable binding.  The dual-key ingress treats this marker as a global legacy
# collision, so quarantined history can suppress a duplicate effect but can
# never authorize a new binding-scoped emission.
OUTBOX_QUARANTINE_BINDING_ID = "outbox-quarantined-unprovable-binding"
