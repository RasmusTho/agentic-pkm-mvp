"""Cross-scope fusion gate (ERE-08, #3183) -- the engine's most likely leak, closed by design.

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/GATE_CROSS_SCOPE_FUSION.md``; ADR-0054 §5 ("cross-scope
fusion is a gated CrossScopeFlow"); ``docs/architecture/cross-scope-flow.md``; ADR-0028
("similarity is not permission").

The Episode Resolution Engine segments **per-scope by default** (ERE-04 already partitions
signals by ``scope`` in :func:`app.episodes.segmenter.fold_signals_into_segments`). A lived
situation spanning two scopes therefore yields **two sibling proposed episodes**, one per scope.
This module adds the gate that decides whether those siblings may instead be *fused* into a single
cross-scope episode, and it enforces the split default when no flow admits a fusion.

Deny-by-default is HARD LAW here (ADR-0054 §5; ADR-0028): constructing a single episode that spans
scopes is itself a ``CrossScopeFlow`` event. It happens **only** when
``mimer_runtime.cross_scope.evaluate`` admits a dedicated :data:`EPISODE_FUSE_OPERATION` under an
explicit typed flow. Absence of a flow is denial -- similarity/co-occurrence is never permission.

One operation, no new authority model (issue Scope: "extends the existing flow contract with an
``episode_fuse`` operation -- no new authority model"). :data:`EPISODE_FUSE_OPERATION` is the single
vocabulary term this slice adds; all three ERE-08 seams (fusion here, cross-scope artifact binding
in :mod:`app.episodes.assignment`, and cross-scope closure-decay influence in
:mod:`app.episodes.closure_decay`) route their cross-scope decision through ``evaluate`` with this
one operation. The authority model is unchanged: a flow's ``allowed_operations`` simply lists
``episode_fuse`` (see ``mimer_runtime.cross_scope.evaluate``).

Three invariants this module enforces (the whole point -- privacy):

1. **Deny-by-default.** :func:`plan_fusions` fuses a cross-scope pair ONLY when ``evaluate`` returns
   ``allowed`` for an explicit flow; every other outcome keeps the scopes split.
2. **Content-free sibling link.** When a cross-scope pair co-occurs but fusion is denied (the
   default), each split episode carries only :data:`CROSS_SCOPE_SIBLING_MARKER` in its
   ``causation`` -- a scope-neutral, directionless token that reveals *only* that a sibling exists,
   never the other scope's title, protagonists, places, ids, or scope name (AC2). Existence-of-a-
   sibling is the maximum leak, and it is symmetric.
3. **Receipt-before-note on allowed fuses.** The caller (:mod:`app.episodes.segmenter`) writes the
   :func:`fusion_receipt_fields` record BEFORE the fused note (see
   :func:`app.episodes.segmenter._emit_proposals_with_fusion_gate`). The fused note itself carries
   the flow reference in its ``causation`` (:data:`FLOW_REF_CAUSATION_PREFIX`).

Denied fusions are **audited, never notified** (issue Constraint): the caller emits an audit log
line for every :class:`DeniedFusion`; nothing is surfaced to the user.

No I/O in this module: it is the pure gate + planning logic (co-occurrence detection, the
``evaluate`` calls, sibling-marker and receipt shaping). The segmenter owns the durable writes
(vault-canonical receipt then fused note) so the guard-at-seam discipline stays in the store.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Mapping, Sequence

from app.episodes.ids import EPISODE_ID_PREFIX

if TYPE_CHECKING:
    from mimer_runtime.cross_scope import CrossScopeDecision

#: The single CrossScopeFlow operation this slice adds to the vocabulary (issue Scope: no new
#: authority model). A flow admits a cross-scope episode operation by listing this in its
#: ``allowed_operations``; absence of such a flow denies (``mimer_runtime.cross_scope.evaluate``).
EPISODE_FUSE_OPERATION = "episode_fuse"

#: Content-free, scope-neutral, directionless sibling marker (AC2). Placed in BOTH split episodes'
#: ``causation`` when a cross-scope pair co-occurs but fusion is denied. It carries NO foreign-scope
#: content -- not the other episode's id, scope, title, protagonists, places, or derived_from. The
#: maximum it reveals is "a co-occurring episode exists in another scope", which is exactly the
#: spec's "existence-of-a-sibling is the maximum leak".
CROSS_SCOPE_SIBLING_MARKER = "cross-scope-sibling"

#: Prefix for the flow reference the fused note carries in ``causation`` (spec: "the fused note
#: carries the flow reference"). Only present on an ALLOWED fuse's note, never on a split sibling.
FLOW_REF_CAUSATION_PREFIX = "cross-scope-flow:"

#: Receipt marker class (audit/provenance record for a governed crossing).
FUSION_RECEIPT_CLASS = "cross_scope_fusion"

#: Fixed, arbitrary namespace UUID for deterministic fused episode ids (Finding 3). Never reused.
_FUSED_EPISODE_ID_NAMESPACE = uuid.UUID("2b6a1e5c-9d4f-4a7b-8c3e-1f0a5d7c2e94")


#: A ``flow_provider`` resolves the explicit typed ``CrossScopeFlow`` (a plain mapping, the shape
#: ``mimer_runtime.cross_scope.evaluate`` reads) for a given directional crossing, or ``None`` when
#: no flow grants it. Production passes NO provider (authoring flow grants is out of scope -- an
#: operator/GOV concern), so every cross-scope decision denies and the split default holds. Tests
#: inject a provider that returns an explicit ``episode_fuse`` flow to exercise the allowed path.
FlowProvider = Callable[[str, str], "Mapping[str, object] | None"]


@dataclass(frozen=True)
class FuseSegment:
    """A closed segment normalized for the fusion gate (a lighter view of
    :class:`app.episodes.segmenter.ClosedSegment` carrying only what the gate needs)."""

    episode_id: str
    scope: str
    start: datetime
    end: datetime
    derived_from: tuple[str, ...] = ()


def deterministic_fused_episode_id(a: FuseSegment, b: FuseSegment) -> str:
    """A STABLE fused ``ep-<uuid>`` derived from the two members' identities (Finding 3).

    Keyed on the sorted ``scope|episode_id`` of both constituent segments -- both of which are
    themselves start-independent, deterministic ids
    (:func:`app.episodes.segmenter._deterministic_episode_id`). So a crash/retry that re-runs
    :func:`plan_fusions` over the same segments mints the SAME fused id, and
    :func:`app.episodes.segmenter._emit_fused_note`'s existence check dedupes the redelivery instead
    of writing a duplicate fused note + receipt. Order-independent: the two members are sorted first,
    so ``(a, b)`` and ``(b, a)`` collapse to one id."""
    members = sorted((f"{a.scope}|{a.episode_id}", f"{b.scope}|{b.episode_id}"))
    basis = "cross_scope_fuse|" + "|".join(members)
    return f"{EPISODE_ID_PREFIX}{uuid.uuid5(_FUSED_EPISODE_ID_NAMESPACE, basis)}"


@dataclass(frozen=True)
class AllowedFusion:
    """A cross-scope pair an explicit flow admitted into ONE fused episode."""

    fused_episode_id: str
    target_scope: str
    source_scope: str
    start: datetime
    end: datetime
    derived_from: tuple[str, ...]
    member_episode_ids: tuple[str, ...]
    flow_ref: str
    evidence_role_in_target: str | None


@dataclass(frozen=True)
class DeniedFusion:
    """A cross-scope pair that co-occurred but was denied a fusion (the default). Carries only the
    scopes + reason for the AUDIT log -- never any episode content. The two split episodes get the
    content-free :data:`CROSS_SCOPE_SIBLING_MARKER` instead."""

    source_scope: str
    target_scope: str
    member_episode_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class FusionPlan:
    allowed: tuple[AllowedFusion, ...] = ()
    denied: tuple[DeniedFusion, ...] = ()
    #: episode_id -> content-free causation additions (only ever :data:`CROSS_SCOPE_SIBLING_MARKER`).
    sibling_markers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: episode_ids consumed by an allowed fuse -- the segmenter skips their split emission.
    fused_member_ids: frozenset[str] = frozenset()


def evaluate_episode_fuse(
    source_scope: str,
    target_scope: str,
    *,
    flow: "Mapping[str, object] | None" = None,
) -> "CrossScopeDecision":
    """Route a cross-scope episode decision through the canonical gate.

    Thin wrapper over ``mimer_runtime.cross_scope.evaluate`` pinned to
    :data:`EPISODE_FUSE_OPERATION`. Imported lazily to keep ``app`` free of an import-time
    dependency on the ``mimer_runtime`` package (mirrors the lazy imports elsewhere in the engine).
    A cross-scope crossing with ``flow=None`` is denied ("similarity is not permission").
    """
    from mimer_runtime import cross_scope

    return cross_scope.evaluate(source_scope, target_scope, EPISODE_FUSE_OPERATION, flow=flow)


def _overlaps(a: FuseSegment, b: FuseSegment) -> bool:
    """Two segments co-occur when their [start, end] intervals intersect."""
    return a.start <= b.end and b.start <= a.end


def _evaluate_pair(
    a: FuseSegment, b: FuseSegment, flow_provider: FlowProvider | None
) -> tuple[object, "Mapping[str, object] | None", str, str]:
    """Evaluate whether a cross-scope pair may fuse, trying BOTH directions (a flow is directional).

    Returns ``(decision, flow, source_scope, target_scope)`` for the first ALLOWED direction, or the
    last (denied) direction's decision so the caller can record its reason. Directions are tried in
    a deterministic order (the segments arrive pre-sorted from :func:`plan_fusions`).
    """
    decision: object | None = None
    flow: "Mapping[str, object] | None" = None
    src = a.scope
    tgt = b.scope
    for source_scope, target_scope in ((a.scope, b.scope), (b.scope, a.scope)):
        flow = flow_provider(source_scope, target_scope) if flow_provider else None
        decision = evaluate_episode_fuse(source_scope, target_scope, flow=flow)
        src, tgt = source_scope, target_scope
        if getattr(decision, "allowed", False):
            return decision, flow, source_scope, target_scope
    return decision, flow, src, tgt


def _flow_ref(flow: "Mapping[str, object] | None", source_scope: str, target_scope: str) -> str:
    """A stable reference to the admitting flow for the receipt + fused note. Prefers the flow's own
    ``flow_id``; falls back to a directional descriptor so the receipt is never reference-less."""
    if isinstance(flow, Mapping):
        flow_id = flow.get("flow_id")
        if isinstance(flow_id, str) and flow_id:
            return flow_id
    return f"{source_scope}->{target_scope}:{EPISODE_FUSE_OPERATION}"


def plan_fusions(
    segments: Sequence[FuseSegment],
    *,
    flow_provider: FlowProvider | None = None,
    mint_id: Callable[[FuseSegment, FuseSegment], str] = deterministic_fused_episode_id,
) -> FusionPlan:
    """Decide, per cross-scope co-occurring pair, fuse-or-split -- deny-by-default.

    For every pair of closed segments in DIFFERENT scopes whose time bounds overlap:

    - :func:`evaluate_episode_fuse` is consulted (both directions). If an explicit flow admits
      ``episode_fuse``, the pair fuses into one :class:`AllowedFusion` (bounds unioned, derived_from
      unioned -- the flow authorizes exactly this crossing) with a freshly minted fused id and the
      flow reference. Both member episode ids are recorded in ``fused_member_ids`` so the segmenter
      skips their split emission.
    - Otherwise (the default -- no flow) the pair is a :class:`DeniedFusion` (audited by the caller,
      never notified) and BOTH episodes get the content-free :data:`CROSS_SCOPE_SIBLING_MARKER` in
      their ``sibling_markers`` entry. The scopes stay split.

    Same-scope pairs are not a cross-scope boundary and are ignored here (ERE-04 already segmented
    them per-scope). v1 is pairwise: a segment already consumed by an allowed fuse is not fused
    again this tick (a later flow-authoring epic owns N-way fusion). Deterministic: segments are
    sorted by ``(scope, start, episode_id)`` before pairing.
    """
    ordered = sorted(segments, key=lambda s: (s.scope, s.start, s.episode_id))
    allowed: list[AllowedFusion] = []
    denied: list[DeniedFusion] = []
    sibling: dict[str, set[str]] = {}
    fused_members: set[str] = set()

    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            a, b = ordered[i], ordered[j]
            if a.scope == b.scope:
                continue
            if not _overlaps(a, b):
                continue
            if a.episode_id in fused_members or b.episode_id in fused_members:
                continue

            decision, flow, source_scope, target_scope = _evaluate_pair(a, b, flow_provider)
            if getattr(decision, "allowed", False):
                # ``target_scope`` is the flow's target -- the fused episode lives there. ``a``/``b``
                # map to source/target by which direction the flow admitted.
                start = min(a.start, b.start)
                end = max(a.end, b.end)
                merged = tuple(sorted(set(a.derived_from) | set(b.derived_from)))
                allowed.append(
                    AllowedFusion(
                        fused_episode_id=mint_id(a, b),
                        target_scope=target_scope,
                        source_scope=source_scope,
                        start=start,
                        end=end,
                        derived_from=merged,
                        member_episode_ids=(a.episode_id, b.episode_id),
                        flow_ref=_flow_ref(flow, source_scope, target_scope),
                        evidence_role_in_target=getattr(decision, "evidence_role_in_target", None),
                    )
                )
                fused_members.update({a.episode_id, b.episode_id})
            else:
                reason = getattr(decision, "reason", "") or "no CrossScopeFlow; similarity is not permission"
                denied.append(
                    DeniedFusion(
                        source_scope=a.scope,
                        target_scope=b.scope,
                        member_episode_ids=(a.episode_id, b.episode_id),
                        reason=reason,
                    )
                )
                sibling.setdefault(a.episode_id, set()).add(CROSS_SCOPE_SIBLING_MARKER)
                sibling.setdefault(b.episode_id, set()).add(CROSS_SCOPE_SIBLING_MARKER)

    return FusionPlan(
        allowed=tuple(allowed),
        denied=tuple(denied),
        sibling_markers={eid: tuple(sorted(marks)) for eid, marks in sibling.items()},
        fused_member_ids=frozenset(fused_members),
    )


def fused_note_causation(fuse: AllowedFusion) -> list[str]:
    """The ``causation`` a fused episode note carries: the flow reference only (spec: "the fused note
    carries the flow reference"). Never any split-sibling marker."""
    return [f"{FLOW_REF_CAUSATION_PREFIX}{fuse.flow_ref}"]


def fusion_receipt_fields(fuse: AllowedFusion, *, recorded_at: str) -> dict[str, object]:
    """The durable receipt record for an allowed fuse, written BEFORE the fused note
    (receipt-before-note). An audit/provenance record of the governed crossing: it references the
    admitting flow and the constituent per-scope episodes, so the fused episode's existence is never
    unaccountable. This is NOT foreign-scope content leaked to a note -- it is the governance receipt
    the crossing produced (``audit_required`` semantics of a CrossScopeFlow use)."""
    return {
        "receipt_class": FUSION_RECEIPT_CLASS,
        "operation": EPISODE_FUSE_OPERATION,
        "fused_episode_id": fuse.fused_episode_id,
        "flow_ref": fuse.flow_ref,
        "source_scope": fuse.source_scope,
        "target_scope": fuse.target_scope,
        "member_episode_ids": list(fuse.member_episode_ids),
        "evidence_role_in_target": fuse.evidence_role_in_target,
        "recorded_at": recorded_at,
    }


__all__ = [
    "CROSS_SCOPE_SIBLING_MARKER",
    "EPISODE_FUSE_OPERATION",
    "FLOW_REF_CAUSATION_PREFIX",
    "FUSION_RECEIPT_CLASS",
    "AllowedFusion",
    "DeniedFusion",
    "FuseSegment",
    "FusionPlan",
    "deterministic_fused_episode_id",
    "evaluate_episode_fuse",
    "fused_note_causation",
    "fusion_receipt_fields",
    "plan_fusions",
]
