"""MVR-06A: the durable instance-local background-binding intent schema.

`docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md` makes background intent a
mechanical registry field that is distinct from registry membership and from any
request/session selection. This module owns only the schema: its value object, its
validation, and its redacted projection. It has no store and no producer of its own;
`VaultRegistryStore` persists it inside the locked, revision-checked registry generation
and `app.instance.background_authority` is the only producer.

States this schema distinguishes (and the parser refuses to conflate):

- **absent** -- a pre-MVR-06 registry. Readers treat it as "not yet migrated".
- **compatibility, handoff pending** -- the MVR-06A staged state. The MVR-05 legacy picker
  bridge (#3163 settings rebind) is still the authoritative single-watcher owner, so no
  binding is materialized here: a stored snapshot could silently diverge from the live
  watcher. ``compatibilityBindingId`` must be null.
- **compatibility, handoff complete** -- the MVR-06B state: the bridge binding has been
  materialized into a nullable ``compatibilityBindingId`` (null is truthful no-vault).
- **explicit** -- a governed add/remove has run. The member set is deduplicated by
  ``vault_binding_id``; an *empty* explicit set is durable idle and is never the same as
  compatibility-uninitialized.

MVR-06A ships producers only for the staged state; the parser already understands every
v1 state so a later MVR-06 child never needs an older MVR-06 image to reinterpret it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.instance.errors import RegistryError

BACKGROUND_INTENT_SCHEMA = "agentic-pkm.background-binding-intent.v1"

#: Registry frontmatter key carrying the intent record.
BACKGROUND_INTENT_KEY = "backgroundIntent"

INTENT_MODE_COMPATIBILITY: Final = "compatibility"
INTENT_MODE_EXPLICIT: Final = "explicit"
INTENT_MODES = frozenset({INTENT_MODE_COMPATIBILITY, INTENT_MODE_EXPLICIT})

#: The compatibility binding is still owned by the MVR-05 legacy picker bridge.
HANDOFF_PENDING: Final = "pending"
#: The MVR-06B supervisor handoff materialized the compatibility binding.
HANDOFF_COMPLETE: Final = "complete"
HANDOFF_STATES = frozenset({HANDOFF_PENDING, HANDOFF_COMPLETE})

#: Provenance of the one-time MVR-06 initialization (the only 06A producer).
PROVENANCE_MVR06_FLOOR_CUTOVER = "mvr06_floor_cutover"
INTENT_PROVENANCES = frozenset(
    {
        PROVENANCE_MVR06_FLOOR_CUTOVER,
        # Reserved for the MVR-06B producers; parsed now so 06A images understand them.
        "compatibility_handoff",
        "compatibility_default",
        "background_intent",
    }
)

IntentMode = Literal["compatibility", "explicit"]
HandoffState = Literal["pending", "complete"]


class BackgroundIntentError(RegistryError):
    """The durable background-intent record is malformed, partial, or ambiguous."""


@dataclass(frozen=True)
class BackgroundBindingIntent:
    """One immutable generation of the durable background-binding intent."""

    revision: int
    mode: IntentMode
    compatibility_handoff: HandoffState
    compatibility_binding_id: str | None
    background_vault_binding_ids: tuple[str, ...]
    provenance: str

    @classmethod
    def staged_compatibility(cls) -> "BackgroundBindingIntent":
        """The MVR-06A initial state: compatibility mode, bridge still authoritative."""

        return cls(
            revision=1,
            mode=INTENT_MODE_COMPATIBILITY,
            compatibility_handoff=HANDOFF_PENDING,
            compatibility_binding_id=None,
            background_vault_binding_ids=(),
            provenance=PROVENANCE_MVR06_FLOOR_CUTOVER,
        )

    @property
    def explicit_empty(self) -> bool:
        return self.mode == INTENT_MODE_EXPLICIT and not self.background_vault_binding_ids

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema": BACKGROUND_INTENT_SCHEMA,
            "revision": self.revision,
            "mode": self.mode,
            "compatibilityHandoff": self.compatibility_handoff,
            "compatibilityBindingId": self.compatibility_binding_id,
            "backgroundVaultBindingIds": list(self.background_vault_binding_ids),
            "provenance": self.provenance,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "BackgroundBindingIntent":
        if not isinstance(payload, Mapping):
            raise BackgroundIntentError("background intent must be a mapping")
        expected = {
            "schema",
            "revision",
            "mode",
            "compatibilityHandoff",
            "compatibilityBindingId",
            "backgroundVaultBindingIds",
            "provenance",
        }
        missing = sorted(expected - set(payload))
        if missing:
            raise BackgroundIntentError(f"partial background intent; missing {missing}")
        unknown = sorted(set(payload) - expected)
        if unknown:
            raise BackgroundIntentError(f"background intent has unknown fields {unknown}")
        if payload["schema"] != BACKGROUND_INTENT_SCHEMA:
            raise BackgroundIntentError("unknown background intent schema")
        revision = payload["revision"]
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise BackgroundIntentError("background intent revision is invalid")
        mode = payload["mode"]
        if mode not in INTENT_MODES:
            raise BackgroundIntentError("background intent mode is invalid")
        handoff = payload["compatibilityHandoff"]
        if handoff not in HANDOFF_STATES:
            raise BackgroundIntentError("background intent handoff state is invalid")
        compatibility = payload["compatibilityBindingId"]
        if compatibility is not None and (
            not isinstance(compatibility, str) or not compatibility.strip()
        ):
            raise BackgroundIntentError("background intent compatibility binding is invalid")
        raw_members = payload["backgroundVaultBindingIds"]
        if not isinstance(raw_members, list) or any(
            not isinstance(item, str) or not item.strip() for item in raw_members
        ):
            raise BackgroundIntentError("background intent members are invalid")
        members = tuple(raw_members)
        if list(members) != sorted(set(members)):
            # The set is deduplicated by vault_binding_id and stored canonically, so a
            # duplicate or reordered list is ambiguous rather than silently normalized.
            raise BackgroundIntentError("background intent members are not canonical")
        provenance = payload["provenance"]
        if provenance not in INTENT_PROVENANCES:
            raise BackgroundIntentError("background intent provenance is invalid")
        if mode == INTENT_MODE_COMPATIBILITY:
            if members:
                raise BackgroundIntentError(
                    "compatibility intent cannot carry explicit members"
                )
            if handoff == HANDOFF_PENDING and compatibility is not None:
                raise BackgroundIntentError(
                    "a pending compatibility handoff cannot materialize a binding"
                )
        else:
            if handoff != HANDOFF_COMPLETE:
                raise BackgroundIntentError(
                    "explicit intent requires the completed compatibility handoff"
                )
            if compatibility is not None:
                raise BackgroundIntentError(
                    "explicit intent cannot retain a compatibility binding"
                )
        return cls(
            revision=revision,
            mode=mode,
            compatibility_handoff=handoff,
            compatibility_binding_id=compatibility,
            background_vault_binding_ids=members,
            provenance=str(provenance),
        )


__all__ = [
    "BACKGROUND_INTENT_KEY",
    "BACKGROUND_INTENT_SCHEMA",
    "HANDOFF_COMPLETE",
    "HANDOFF_PENDING",
    "INTENT_MODE_COMPATIBILITY",
    "INTENT_MODE_EXPLICIT",
    "PROVENANCE_MVR06_FLOOR_CUTOVER",
    "BackgroundBindingIntent",
    "BackgroundIntentError",
]
