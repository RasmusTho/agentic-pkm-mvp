"""Heimdal screen derivation stage -- frames become one governed activity observation.

SCREEN-02 (#3344), specified by
`docs/HEIMDAL_SCREEN_STREAM/DERIVE_ACTIVITY_OBSERVATIONS.md`. This is the
in-seam derivation stage: the screen analog of the ASR stage
(`app.heimdal.asr_stage`), and it follows that module's shape deliberately --
gated raw read in, stage-local derivation, no second writer.

What this module owns (issue Acceptance Criteria):

- **Gated raw read only (HEIM-5).** Frames are resolved exclusively through
  `app.heimdal.raw_read_gate.read_raw_record` with reader id
  ``"screen_derivation"``; this module never touches the raw store, a
  filesystem path, or a decryption key path of its own, so every frame read
  leaves a receipt and an unallowlisted reader gets bytes from nowhere.
- **Local-only model routing (RUNTIME_MODEL_POSTURE §1/§4.2).** Screen
  derivation is an always-on loop, so its task kind
  (:data:`TASK_KIND`) is structurally paid-ineligible.
  :func:`resolve_derivation_route` is the compile step: it reads the declared
  provider census and **rejects** any policy that assigns this task kind to a
  paid provider (:class:`PaidRouteRejectedError`) before a single frame is
  read. The resolved route is a local vision model. There is no cloud code
  path in this module to degrade into -- that is the structural off-switch for
  the raw-pixel egress seam, and it is declared here as
  :data:`DECLARED_EGRESS` (HEIM-12: zero raw-class egress).
- **The destination is validated, not just the provider name.** A census entry
  proves a provider *name* is local; it cannot prove that the socket a
  decrypted frame is about to be written to is on this machine.
  :func:`resolve_local_vision_endpoint` closes that half: the resolved endpoint
  must be loopback, or a hostname the operator explicitly declared host-local
  (:data:`HOST_LOCAL_VISION_ALLOWLIST_ENV`), or the derivation is refused
  (:class:`RawEgressRefusedError`) before the frame is attached to any request.
  The request also runs with ``trust_env`` disabled, so an ambient proxy cannot
  carry a loopback-addressed frame off the host.
- **Span coalescing (INV-SCREEN-E).** Consecutive frames whose activity is
  unchanged collapse into one span observation with a real
  ``observed_at_start``/``observed_at_end``. A boundary is created on **any**
  dimension shift -- frontmost app, window/document, capture scope, derived
  goal, or an axis a context provider declares itself. Unknown never equals
  unknown: an empty dimension forces a boundary rather than merging. Frames out
  of capture order force a boundary too. Over-segmentation is the preferred
  direction: a spurious boundary is a cheap downstream re-cut, a lost one is
  unrecoverable.
- **Provenance stamped in the same write, or no write (INV-SCREEN-B).** A span
  that derived text but cannot stamp complete provenance (machine-bearing
  sensor, capture chain, content identity from the read receipt, observed-at
  window, `stage_versions` + `model_ref`) raises
  :class:`UnprovenancedObservationError` and publishes nothing.
- **Governed publish, reused not reimplemented.** Payloads are assembled and
  published through `app.heimdal.publish.publish_full_observation` (schema
  validated, ``content_hash`` stamped in the same durable write,
  revision-aware idempotency key). The Mimer candidate projector consumes the
  observation log on its own cursor -- this stage never writes a note.

Out of scope for this slice: the capture endpoint and schema (SCREEN-01, which
lands the frames this stage reads); the client (SCREEN-03); ERE consumption of
the spans (SCREEN-04); the time-spend rollup (SCREEN-05); the control surface
and the `screen_coalesce_*` sensitivity settings (SCREEN-06). Frame discard
after a successful publish is bounded by SCREEN-01's retention buffer
(`app.heimdal.retention.enforce_screen_frame_retention`), not re-implemented
here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

from app.components.settings.providers_loader import ProviderCensus, load_provider_census
from app.heimdal.publish import assemble_observation_payload, publish_full_observation
from app.heimdal.raw_read_gate import raw_ref_for, read_raw_record
from app.heimdal.screen_context_providers import (
    ContextContribution,
    FrameContext,
    collect_context,
)

#: The always-on task kind this stage routes under. Structurally
#: ``paid_eligible: false`` (RUNTIME_MODEL_POSTURE §4.2 floor 1).
TASK_KIND = "heimdal.screen_derivation"

#: This stage's reader identity at the gated raw-read path (HEIM-5). Must be on
#: ``HEIMDAL_RAW_READ_ALLOWLIST`` for any frame to be readable at all.
READER_ID = "screen_derivation"

#: The stage name used in ``provenance.stage_versions`` for replay lineage.
STAGE_NAME = "screen_derivation"

#: Bumped when this stage's own summarizing/coalescing logic changes in a way
#: that would produce a materially different observation for the same frames
#: and model -- folded into ``stage_versions`` alongside the model id so a
#: replay after a stage change is legible as a distinct stage version.
ENGINE_VERSION = "heimdal-screen-derivation-v1"

#: The declared local vision route (census-declared, tier ``local``).
LOCAL_VISION_PROVIDER = "ollama"
LOCAL_VISION_MODEL = "llava:7b"

OBSERVATION_TOPIC = "heimdal.observation.published"
PUBLISH_SOURCE = "heimdal.screen_derivation"

#: HEIM-12 `heim_declared_egress`: the structured, machine-checkable egress
#: posture for this stage. Raw-class evidence (the frames themselves) never
#: leaves the host trust boundary; the only destination the stage has is the
#: host-local vision model it compiles a route to. Asserted by
#: ``tests/invariants/test_heimdal_seam.py::test_declared_egress``.
DECLARED_EGRESS: Mapping[str, Any] = MappingProxyType(
    {
        "stage": TASK_KIND,
        "raw_class_egress": False,
        "raw_classes": ("screen_frame",),
        "destinations": ("host_local_vision_model",),
        "basis": (
            "docs/HEIMDAL/FABLE_COMPANION.md :: HEIM-12; "
            "docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md :: 4.2"
        ),
    }
)

#: The four segmenter dimensions a span is keyed on (INV-SCREEN-E / SCREEN-04).
SPAN_DIMENSIONS: Tuple[str, ...] = ("app", "window", "scope", "goal")


class PaidRouteRejectedError(RuntimeError):
    """Raised when a policy would assign this always-on task kind to a paid route.

    The stage-invariant floor (RUNTIME_MODEL_POSTURE §4.2): no posture stage
    makes an always-on loop cloud-routable. Fail at compile, not at 3 a.m. --
    this is raised before any frame is read.
    """


class LocalVisionUnavailableError(RuntimeError):
    """Raised when the local vision model cannot produce an activity summary.

    Fail-loud, mirroring `app.heimdal.asr_stage.LocalAsrUnavailableError`:
    there is no cloud fallback in this module to degrade into. A caller
    leaves the frames buffered (SCREEN-01's retention bound still applies) and
    surfaces the failure to the operator.
    """


class UnprovenancedObservationError(RuntimeError):
    """Raised when a derived span cannot stamp complete provenance (INV-SCREEN-B).

    The observation must outlive its frames, so an observation that cannot say
    which machine, which capture chain, which raw evidence, and which stage
    version produced it is never published.
    """


class ScreenFrameUndecodableError(ValueError):
    """Raised when a gated read does not yield a decodable screen frame bundle."""


class ContextDimensionConflictError(ValueError):
    """Raised when two context providers claim the same segmenter dimension.

    Silent last-writer-wins here would move a span boundary invisibly, so the
    ambiguity is refused instead of resolved by registration order.
    """


@dataclass(frozen=True)
class DerivationRoute:
    """The compiled model route for one derivation tick."""

    task_kind: str
    provider: str
    model: str
    model_ref: str
    tier: str
    paid_eligible: bool


@dataclass(frozen=True)
class ScreenFrame:
    """One durable frame handed to the stage: an opaque raw handle plus its governance metadata.

    Deliberately carries no pixels and no path -- the bytes are reachable only
    through the gated read this stage performs from ``raw_ref``.
    """

    raw_ref: str
    observed_at: str
    sensor: Mapping[str, str]
    capture_chain: Tuple[str, ...]
    consent: Mapping[str, Any]
    scope_hint: Optional[str] = None
    #: Which clock ``observed_at`` came from. ``inferred`` when the capture
    #: carried no device clock and ingest time stood in for it -- timing
    #: uncertainty is stated, never silently faked (HEIM-10).
    clock_basis: str = "device_metadata"


@dataclass(frozen=True)
class VisionRequest:
    """The exact request handed to the local vision model (and to a test runner)."""

    model: str
    prompt: str
    image: Optional[str]
    facts: Tuple[str, ...]
    dimensions: Mapping[str, str]


@dataclass(frozen=True)
class DerivedActivity:
    """One frame's derived activity: what the owner is doing, and how sure we are."""

    summary: str
    goal: str
    mentions: Tuple[Mapping[str, Any], ...]
    confidence: float
    calibration: str


@dataclass(frozen=True)
class ActivitySpan:
    """One coalesced run of consecutive frames sharing every segmenter dimension."""

    dimensions: Mapping[str, str]
    observed_at_start: str
    observed_at_end: str
    frame_count: int
    raw_refs: Tuple[str, ...]
    content_identities: Tuple[str, ...]
    facts: Tuple[str, ...]
    provider_mentions: Tuple[Mapping[str, Any], ...]
    activity: DerivedActivity
    frame: ScreenFrame


@dataclass(frozen=True)
class ScreenDerivationTick:
    """The result of one derivation pass over a batch of frames."""

    route: DerivationRoute
    frames_read: int
    observations_published: int
    coalesced: int
    spans: Tuple[ActivitySpan, ...]


# ---------------------------------------------------------------------------
# Model routing -- the always-on-local floor, compiled
# ---------------------------------------------------------------------------


def resolve_derivation_route(*, census: Optional[ProviderCensus] = None) -> DerivationRoute:
    """Compile the model route for :data:`TASK_KIND`, or refuse.

    The declared provider census is the single source for provider tiers and
    per-task-kind paid eligibility (RUNTIME_MODEL_POSTURE §2). This function is
    the compile step the floor calls for: a census in which ANY provider claims
    this always-on task kind as paid-eligible is rejected
    (:class:`PaidRouteRejectedError`), and the resolved provider must be
    declared ``tier: local``. The concrete local vision model must be declared
    in the census too, so the route is never an undeclared string.
    """
    resolved = census if census is not None else load_provider_census()

    claimed_by = [
        provider.id for provider in resolved.providers if TASK_KIND in provider.paid_eligible_task_kinds
    ]
    if claimed_by:
        raise PaidRouteRejectedError(
            f"Routing refused: task kind {TASK_KIND!r} is an always-on loop and is "
            f"structurally paid-ineligible (RUNTIME_MODEL_POSTURE 4.2 floor 1), but the "
            f"declared census marks it paid-eligible for {sorted(claimed_by)!r}. No posture "
            "stage makes an always-on loop cloud-routable; fix the census, not the stage."
        )

    provider = resolved.provider(LOCAL_VISION_PROVIDER)
    if provider.tier != "local":
        raise PaidRouteRejectedError(
            f"Routing refused: task kind {TASK_KIND!r} resolves to provider "
            f"{LOCAL_VISION_PROVIDER!r}, which the census declares tier {provider.tier!r}, "
            "not 'local'. Raw pixels never leave the host trust boundary (HEIM-12)."
        )

    model = next((item for item in provider.models if item.id == LOCAL_VISION_MODEL), None)
    if model is None:
        raise PaidRouteRejectedError(
            f"Routing refused: local vision model {LOCAL_VISION_MODEL!r} is not declared for "
            f"provider {LOCAL_VISION_PROVIDER!r} in the provider census. The route must name a "
            "declared model, never an ad-hoc one."
        )

    return DerivationRoute(
        task_kind=TASK_KIND,
        provider=provider.id,
        model=model.id,
        model_ref=model.effective_identity,
        tier=provider.tier,
        paid_eligible=False,
    )


# ---------------------------------------------------------------------------
# Egress destination -- the other half of the local-only guarantee
# ---------------------------------------------------------------------------

#: Addresses that are host-local by construction.
_LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "::1", "localhost", "localhost.localdomain"})

#: Operator declaration that a named, non-loopback endpoint is still inside the
#: host trust boundary -- the container-network case (`http://ollama:11434` in
#: this repo's own compose files). Comma-separated hostnames. Empty/unset means
#: loopback only; this never widens silently, exactly like
#: ``HEIMDAL_RAW_READ_ALLOWLIST``.
HOST_LOCAL_VISION_ALLOWLIST_ENV = "HEIMDAL_SCREEN_VISION_HOST_LOCAL_HOSTS"


class RawEgressRefusedError(RuntimeError):
    """Raised when the resolved vision endpoint is not provably host-local.

    HEIM-12 / :data:`DECLARED_EGRESS`: raw-class evidence never leaves the host
    trust boundary. The provider census proves a provider *name* is
    ``tier: local``; it cannot prove that the socket the stage is about to send
    a decrypted frame to is on this machine. This is that second check, and it
    fails closed -- refused before the frame is attached to any request.
    """


def _declared_host_local_hostnames() -> frozenset:
    raw = os.getenv(HOST_LOCAL_VISION_ALLOWLIST_ENV, "")
    return frozenset(item.strip().lower() for item in raw.split(",") if item.strip())


def resolve_local_vision_endpoint() -> str:
    """Resolve the local vision endpoint, refusing any non-host-local destination.

    Reads only the Ollama-specific host variables -- deliberately not the
    generic runtime chat env, which is provider-routable and could resolve to a
    remote provider. The resolved address must then be loopback, or a hostname
    the operator explicitly declared host-local via
    :data:`HOST_LOCAL_VISION_ALLOWLIST_ENV`. Anything else raises
    :class:`RawEgressRefusedError` before a frame is transmitted.
    """
    host = (
        os.getenv("OLLAMA_BASE_URL", "").strip()
        or os.getenv("OLLAMA_HOST", "").strip()
        or os.getenv("OLLAMA_URL", "").strip()
    )
    if not host:
        raise LocalVisionUnavailableError(
            "No local model host configured (OLLAMA_BASE_URL, OLLAMA_HOST, or OLLAMA_URL). "
            "Screen derivation is local-only -- there is no remote fallback; the frames stay "
            "buffered until the local vision model is available."
        )

    candidate = host if "://" in host else f"http://{host}"
    hostname = (urlparse(candidate).hostname or "").strip().lower()
    if not hostname:
        raise RawEgressRefusedError(
            f"Refusing to derive: vision endpoint {host!r} names no resolvable host, so it "
            "cannot be proven host-local (HEIM-12). No frame was transmitted."
        )
    if hostname in _LOOPBACK_HOSTNAMES or hostname in _declared_host_local_hostnames():
        return host

    raise RawEgressRefusedError(
        f"Refusing to derive: vision endpoint host {hostname!r} is not loopback and is not "
        f"declared host-local in {HOST_LOCAL_VISION_ALLOWLIST_ENV}. Raw screen frames never "
        "leave the host trust boundary (HEIM-12, DECLARED_EGRESS raw_class_egress=false). "
        "No frame was transmitted. Point the stage at a host-local model, or declare the "
        "endpoint host-local explicitly if it really is inside this machine's boundary."
    )


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------


def screen_frame_from_raw_record(record: Any, *, observed_at: Optional[str] = None) -> ScreenFrame:
    """Build this stage's frame handle from a durable raw record.

    ``record`` is duck-typed against `app.heimdal.raw_store.RawRecord` (id,
    ``content_identity``, ``capture_chain``, ``sensor``, ``consent``,
    ``ingested_at``) rather than imported, so this module keeps exactly one
    dependency on the raw layer: the gate. ``observed_at`` defaults to the
    record's ingest time when the capture did not carry a device clock.
    """
    return ScreenFrame(
        raw_ref=raw_ref_for(record),
        observed_at=observed_at or _iso_utc(record.ingested_at),
        sensor=dict(record.sensor or {}),
        capture_chain=tuple(record.capture_chain or ()),
        consent=dict(record.consent or {}),
        scope_hint=str((record.payload or {}).get("scope") or "") or None,
        clock_basis="device_metadata" if observed_at else "inferred",
    )


def _iso_utc(value: Any) -> str:
    moment = value.astimezone(timezone.utc)
    return moment.isoformat().replace("+00:00", "Z")


def _as_moment(value: str) -> Optional[datetime]:
    """Parse an observed-at stamp, or None when it is not a parseable instant."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _decode_frame_bundle(plaintext: bytes) -> Mapping[str, Any]:
    """Decode one gated read into the frame bundle the client captured.

    SCREEN-01 lands the client bundle as canonical JSON; the frontmost-app
    metadata may sit at the top level or inside ``raw``. Anything that is not a
    JSON object is refused loudly rather than derived from guesswork.
    """
    try:
        decoded = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScreenFrameUndecodableError(
            f"Screen frame bundle is not decodable JSON: {exc}"
        ) from exc
    if not isinstance(decoded, dict):
        raise ScreenFrameUndecodableError(
            f"Screen frame bundle must be a JSON object, got {type(decoded).__name__}"
        )
    merged: Dict[str, Any] = dict(decoded)
    nested = decoded.get("raw")
    if isinstance(nested, dict):
        merged.update(nested)
    return merged


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def _merge_contributions(
    contributions: Sequence[ContextContribution],
) -> Tuple[Tuple[str, ...], List[Dict[str, Any]], Dict[str, str]]:
    """Fold every provider's contribution, refusing a silent dimension overwrite.

    Last-writer-wins on the segmenter dimensions would let a second provider
    overwrite provider #1's axis and merge a real boundary away (INV-SCREEN-E,
    the unrecoverable direction), so a collision is a loud error rather than a
    quiet reassignment.
    """
    facts: List[str] = []
    mentions: List[Dict[str, Any]] = []
    dimensions: Dict[str, str] = {}
    claimed_by: Dict[str, str] = {}
    for contribution in contributions:
        facts.extend(contribution.facts)
        mentions.extend(dict(mention) for mention in contribution.mentions)
        for key, value in contribution.dimensions.items():
            if key in claimed_by:
                raise ContextDimensionConflictError(
                    f"Context provider {contribution.provider!r} sets segmenter dimension "
                    f"{key!r}, which {claimed_by[key]!r} already set. Two providers cannot own "
                    "one dimension: the later write would silently move a span boundary."
                )
            claimed_by[key] = contribution.provider
            dimensions[key] = str(value)
    return tuple(facts), mentions, dimensions


def _build_prompt(facts: Sequence[str]) -> str:
    lines = [
        "Describe in one short sentence what the operator is doing on this screen.",
        "Answer as JSON with keys: summary, goal, mentions, confidence.",
        "Name apps, documents, projects, and URLs you can see as mentions.",
    ]
    if facts:
        lines.append("Host context:")
        lines.extend(f"- {fact}" for fact in facts)
    return "\n".join(lines)


def _invoke_local_vision(
    request: VisionRequest,
    *,
    vision_runner: Optional[Callable[[VisionRequest], Mapping[str, Any]]],
) -> Mapping[str, Any]:
    """Call the host-local vision model; never anything off-host.

    ``vision_runner`` is the test/injection seam (called directly). The
    production path posts to the locally served model host resolved from
    ``OLLAMA_BASE_URL`` / ``OLLAMA_HOST`` / ``OLLAMA_URL`` -- deliberately not
    the generic runtime chat env, because that one is provider-routable and
    could resolve off-host. Any failure raises
    :class:`LocalVisionUnavailableError`; there is no except branch in this
    module that reaches for a remote model.
    """
    if vision_runner is not None:
        try:
            return dict(vision_runner(request))
        except Exception as exc:  # pragma: no cover - mirrors the production branch
            raise LocalVisionUnavailableError(
                f"Local vision (injected runner) failed for model {request.model!r}: {exc}"
            ) from exc

    # Resolve AND validate the destination before the frame is touched: the
    # census proves a provider *name* is local, it cannot prove a socket is.
    endpoint = resolve_local_vision_endpoint()

    message: Dict[str, Any] = {"role": "user", "content": request.prompt}
    if request.image:
        message["images"] = [request.image]
    try:
        content = _post_local_vision(
            endpoint,
            {"model": request.model, "messages": [message], "stream": False},
        )
    except Exception as exc:
        raise LocalVisionUnavailableError(
            f"Local vision model {request.model!r} failed on the host: {exc}. Screen derivation "
            "is local-only -- the frames stay buffered and the operator must be notified."
        ) from exc

    return _parse_vision_content(content)


def _post_local_vision(endpoint: str, body: Mapping[str, Any]) -> Any:
    """POST one already-validated host-local vision request.

    ``trust_env`` is disabled deliberately: `requests` otherwise honours
    ``HTTP_PROXY``/``HTTPS_PROXY``/``ALL_PROXY`` from the environment, which
    would let an ambient proxy carry a loopback-addressed raw frame off the
    host after :func:`resolve_local_vision_endpoint` proved the address itself
    host-local. Validating the address and then handing the request to an
    env-configurable proxy would defeat the whole guarantee.
    """
    import requests  # type: ignore[import-untyped]

    session = requests.Session()
    session.trust_env = False
    try:
        response = session.post(
            endpoint.rstrip("/") + "/api/chat",
            json=dict(body),
            timeout=float(os.getenv("HEIMDAL_SCREEN_VISION_TIMEOUT", "120")),
        )
        response.raise_for_status()
        return response.json()["message"]["content"]
    finally:
        session.close()


def _parse_vision_content(content: Any) -> Mapping[str, Any]:
    """Read the model's reply, tolerating a plain-text answer."""
    if isinstance(content, Mapping):
        return dict(content)
    text = str(content or "").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"summary": text}
    if isinstance(parsed, dict):
        return parsed
    return {"summary": text}


def _normalize_activity(output: Mapping[str, Any]) -> DerivedActivity:
    summary = str(output.get("summary") or "").strip()
    if not summary:
        raise LocalVisionUnavailableError(
            "Local vision model returned no activity summary; nothing is derived and nothing "
            "is published (never an empty observation)."
        )
    raw_mentions = output.get("mentions") or ()
    mentions: List[Mapping[str, Any]] = []
    if isinstance(raw_mentions, Sequence) and not isinstance(raw_mentions, (str, bytes)):
        for mention in raw_mentions:
            if isinstance(mention, Mapping) and str(mention.get("surface_form") or "").strip():
                mentions.append(dict(mention))
    score = output.get("confidence")
    confidence = float(score) if isinstance(score, (int, float)) else 0.5
    confidence = max(0.0, min(1.0, confidence))
    return DerivedActivity(
        summary=summary,
        goal=str(output.get("goal") or "").strip(),
        mentions=tuple(mentions),
        # Never claim a calibrated score: a vision model's self-reported
        # confidence is a heuristic (FABLE_COMPANION §2.1 / HEIM-6).
        confidence=confidence,
        calibration="heuristic",
    )


def _derive_frame(
    frame: ScreenFrame,
    *,
    route: DerivationRoute,
    key: Optional[bytes],
    vision_runner: Optional[Callable[[VisionRequest], Mapping[str, Any]]],
) -> Tuple[DerivedActivity, Dict[str, str], Tuple[str, ...], List[Dict[str, Any]], str]:
    """Read one frame through the gate and derive its activity."""
    gated = read_raw_record(
        frame.raw_ref,
        reader=READER_ID,
        purpose="screen_derivation",
        key=key,
    )
    bundle = _decode_frame_bundle(gated.plaintext)
    contributions = collect_context(
        FrameContext(raw_ref=frame.raw_ref, observed_at=frame.observed_at, bundle=bundle)
    )
    facts, provider_mentions, dimensions = _merge_contributions(contributions)

    image = bundle.get("frame")
    request = VisionRequest(
        model=route.model,
        prompt=_build_prompt(facts),
        image=str(image) if image is not None else None,
        facts=facts,
        dimensions=dict(dimensions),
    )
    activity = _normalize_activity(_invoke_local_vision(request, vision_runner=vision_runner))
    dimensions["goal"] = activity.goal
    return activity, dimensions, facts, provider_mentions, gated.receipt.content_identity


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-") or "unknown"


def _entity_mentions(span: ActivitySpan) -> List[Dict[str, Any]]:
    mentions: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for mention in (*span.activity.mentions, *span.provider_mentions):
        surface = str(mention.get("surface_form") or "").strip()
        if not surface:
            continue
        kind = str(mention.get("kind_hint") or "thing")
        mention_id = f"screen:{_slug(kind)}:{_slug(surface)}"
        if mention_id in seen:
            continue
        seen.add(mention_id)
        mentions.append(
            {
                "mention_id": mention_id,
                "surface_form": surface,
                "kind_hint": kind,
                # Derivation surfaces mentions; it never mints a canonical
                # identity (HEIM-6/HEIM-11). Resolution is a later stage's job.
                "resolution": "unresolved",
            }
        )
    return mentions


def _render_content(span: ActivitySpan) -> str:
    """Markdown-first, minimized: one activity line plus its host context."""
    lines = [span.activity.summary]
    if span.facts:
        lines.append("")
        lines.extend(f"- {fact}" for fact in span.facts)
    return "\n".join(lines)


def _observation_id(episode_id: str, span: ActivitySpan) -> str:
    """Identity of one span, derived from the EVIDENCE it covers.

    Deliberately not derived from the model's text: a local vision model
    rewording its summary by one token on replay would otherwise mint a new,
    unlinked identity and append a duplicate observation for the same frames
    (double-counted time-spend downstream). Keyed on the covered frames'
    content identities, a replay lands on the same ``observation_id``, so
    differing model text becomes a genuine revision through the
    ``stage_versions`` fingerprint instead of a second unrelated row.
    """
    digest = hashlib.sha256(
        "|".join([episode_id, *span.content_identities]).encode("utf-8")
    ).hexdigest()
    return f"screen-obs-{digest[:32]}"


def _assert_complete_provenance(provenance: Mapping[str, Any], span: ActivitySpan) -> None:
    """INV-SCREEN-B: refuse to publish an observation that cannot outlive its frames."""
    sensor = provenance.get("sensor")
    if not isinstance(sensor, Mapping):
        raise UnprovenancedObservationError(
            "Refusing to publish: provenance carries no sensor block; the observation could "
            "not say which machine observed it."
        )
    for field_name in ("adapter", "version", "machine"):
        if not str(sensor.get(field_name) or "").strip():
            raise UnprovenancedObservationError(
                f"Refusing to publish: provenance sensor is missing {field_name!r}; complete "
                "provenance is stamped in the same write as the observation or not at all "
                "(INV-SCREEN-B)."
            )
    if not provenance.get("capture_chain"):
        raise UnprovenancedObservationError(
            "Refusing to publish: provenance carries no capture_chain."
        )
    if not str(provenance.get("content_identity") or "").strip():
        raise UnprovenancedObservationError(
            "Refusing to publish: provenance carries no content_identity from the gated read."
        )
    if not str(provenance.get("model_ref") or "").strip():
        raise UnprovenancedObservationError(
            "Refusing to publish: provenance carries no model_ref for the derivation."
        )
    stage_versions = provenance.get("stage_versions")
    if not isinstance(stage_versions, Mapping) or not stage_versions.get(STAGE_NAME):
        raise UnprovenancedObservationError(
            f"Refusing to publish: provenance carries no {STAGE_NAME!r} stage version."
        )
    if not span.observed_at_start or not span.observed_at_end:
        raise UnprovenancedObservationError(
            "Refusing to publish: the observed-at window is incomplete."
        )
    start = _as_moment(span.observed_at_start)
    end = _as_moment(span.observed_at_end)
    if start is not None and end is not None and end < start:
        raise UnprovenancedObservationError(
            f"Refusing to publish: the observed-at window runs backwards "
            f"({span.observed_at_start} -> {span.observed_at_end}). A span cannot end before "
            "it began (HEIM-10 bitemporal honesty)."
        )


def _publish_span(
    span: ActivitySpan,
    *,
    episode_id: str,
    route: DerivationRoute,
) -> bool:
    content = _render_content(span)
    stage_versions = {STAGE_NAME: f"{route.model}@{ENGINE_VERSION}"}
    provenance: Dict[str, Any] = {
        "sensor": dict(span.frame.sensor),
        "capture_chain": list(span.frame.capture_chain),
        "content_identity": span.content_identities[0] if span.content_identities else "",
        "content_identities": list(span.content_identities),
        "stage_versions": stage_versions,
        "model_ref": route.model_ref,
        "raw_refs": list(span.raw_refs),
    }
    _assert_complete_provenance(provenance, span)

    mention_scores = [
        float(mention["confidence"])
        for mention in span.activity.mentions
        if isinstance(mention.get("confidence"), (int, float))
    ]
    payload = assemble_observation_payload(
        observation_id=_observation_id(episode_id, span),
        episode_id=episode_id,
        observed_at_start=span.observed_at_start,
        observed_at_end=span.observed_at_end,
        clock_basis=span.frame.clock_basis,
        # Deliberately unset: the schema documents `sequence` as monotone
        # WITHIN THE EPISODE, and this stage only ever sees one tick's batch.
        # A tick-local counter would be a false claim, and because it is folded
        # into the publish fingerprint it would also make a replayed span at a
        # different batch index derive a fresh idempotency key and duplicate the
        # row -- the exact failure the idempotency key exists to prevent.
        sequence=None,
        attributions=[
            {
                "mention_id": "operator",
                "role": "recorder",
                "resolution": "resolved",
                "basis": "capture_context",
            }
        ],
        entity_mentions=_entity_mentions(span),
        modality="screen",
        content=content,
        content_structure={
            "span": {
                "frame_count": span.frame_count,
                "dimensions": dict(span.dimensions),
                "raw_refs": list(span.raw_refs),
            }
        },
        raw_ref=span.raw_refs[0] if span.raw_refs else None,
        confidence={
            "attribution": {
                "score": 1.0,
                "calibration": "by_construction",
                "method": "single_operator_capture",
            },
            "activity_summary": {
                "score": span.activity.confidence,
                "calibration": span.activity.calibration,
                "method": "local_vision",
                "model_ref": route.model_ref,
            },
            "entity_mention": {
                "score": (sum(mention_scores) / len(mention_scores)) if mention_scores else 0.5,
                "calibration": "heuristic",
                "method": "local_vision",
                "model_ref": route.model_ref,
            },
        },
        provenance=provenance,
        consent=dict(span.frame.consent),
        sensitivity="private",
        scope_hint=span.frame.scope_hint,
    )
    row = publish_full_observation(
        topic=OBSERVATION_TOPIC,
        payload=payload,
        source=PUBLISH_SOURCE,
        stage_versions=stage_versions,
    )
    return row is not None


# ---------------------------------------------------------------------------
# The stage entrypoint
# ---------------------------------------------------------------------------


class _OpenSpan:
    """Mutable accumulator for the span currently being coalesced."""

    def __init__(
        self,
        *,
        frame: ScreenFrame,
        dimensions: Mapping[str, str],
        facts: Tuple[str, ...],
        activity: DerivedActivity,
        provider_mentions: Sequence[Mapping[str, Any]],
        content_identity: str,
    ) -> None:
        self.frame = frame
        self.dimensions = dict(dimensions)
        self.facts = facts
        self.activity = activity
        self.provider_mentions = [dict(mention) for mention in provider_mentions]
        self.observed_at_start = frame.observed_at
        self.observed_at_end = frame.observed_at
        self.raw_refs: List[str] = [frame.raw_ref]
        self.content_identities: List[str] = [content_identity]

    def extend(self, frame: ScreenFrame, content_identity: str) -> None:
        self.observed_at_end = frame.observed_at
        self.raw_refs.append(frame.raw_ref)
        self.content_identities.append(content_identity)

    @property
    def frame_count(self) -> int:
        return len(self.raw_refs)

    def close(self) -> ActivitySpan:
        return ActivitySpan(
            dimensions=dict(self.dimensions),
            observed_at_start=self.observed_at_start,
            observed_at_end=self.observed_at_end,
            frame_count=self.frame_count,
            raw_refs=tuple(self.raw_refs),
            content_identities=tuple(self.content_identities),
            facts=self.facts,
            provider_mentions=tuple(self.provider_mentions),
            activity=self.activity,
            frame=self.frame,
        )


def _span_key(dimensions: Mapping[str, str]) -> Tuple[Tuple[str, str], ...]:
    """Key a span on EVERY contributed dimension, not just the four built-ins.

    A provider that declares an axis of its own (the registry explicitly invites
    this) must be able to cut a span; ignoring its dimension would merge a real
    boundary away. Extra dimensions can only ever add boundaries, which is the
    preferred direction.
    """
    return tuple(sorted((str(key), str(value)) for key, value in dimensions.items()))


def _coalesces_into(previous: Mapping[str, str], current: Mapping[str, str]) -> bool:
    """Whether ``current`` continues ``previous``'s activity.

    Unknown is never equal to unknown: if any dimension is empty on either side
    (a client without Accessibility permission reports no window title; a failed
    frontmost-app lookup reports no app; a model that names no goal), the frames
    are NOT merged. Missing metadata degrades to over-segmentation -- a cheap
    downstream re-cut -- never to one observation claiming a single activity
    across an arbitrarily long window.
    """
    if _span_key(previous) != _span_key(current):
        return False
    return all(str(value).strip() for value in current.values())


def _runs_backwards(open_end: str, candidate: str) -> bool:
    """Whether extending a span with ``candidate`` would invert its window.

    Frames are expected in capture order; an out-of-order frame forces a
    boundary instead of publishing a span that ends before it began.
    """
    end = _as_moment(open_end)
    moment = _as_moment(candidate)
    if end is None or moment is None:
        return False
    return moment < end


def derive_activity_observations(
    frames: Sequence[ScreenFrame],
    *,
    episode_id: str,
    vision_runner: Optional[Callable[[VisionRequest], Mapping[str, Any]]] = None,
    key: Optional[bytes] = None,
) -> ScreenDerivationTick:
    """Derive and publish activity observations for one batch of frames.

    The production entrypoint. Compiles the local-only route first (so a paid
    assignment fails before any raw byte is read), then, per frame: gated raw
    read -> local context providers -> local vision model -> span coalescing.
    A span is published through the governed path when the next frame shifts a
    segmenter dimension, and the final open span is flushed at the end of the
    batch (over-segmentation is the preferred direction -- SCREEN-04 can merge
    downstream, it cannot invent a boundary that was never recorded).

    ``vision_runner`` is the injection seam for tests and for a host that
    serves the local model differently; production callers omit it.
    """
    if not isinstance(episode_id, str) or not episode_id.strip():
        raise ValueError(f"episode_id must be a non-empty string, got {episode_id!r}")

    route = resolve_derivation_route()

    spans: List[ActivitySpan] = []
    published = 0
    coalesced = 0
    open_span: Optional[_OpenSpan] = None

    for frame in frames:
        activity, dimensions, facts, provider_mentions, content_identity = _derive_frame(
            frame,
            route=route,
            key=key,
            vision_runner=vision_runner,
        )
        if (
            open_span is not None
            and _coalesces_into(open_span.dimensions, dimensions)
            and not _runs_backwards(open_span.observed_at_end, frame.observed_at)
        ):
            open_span.extend(frame, content_identity)
            coalesced += 1
            continue
        if open_span is not None:
            span = open_span.close()
            spans.append(span)
            published += int(_publish_span(span, episode_id=episode_id, route=route))
        open_span = _OpenSpan(
            frame=frame,
            dimensions=dimensions,
            facts=facts,
            activity=activity,
            provider_mentions=provider_mentions,
            content_identity=content_identity,
        )

    if open_span is not None:
        span = open_span.close()
        spans.append(span)
        published += int(_publish_span(span, episode_id=episode_id, route=route))

    return ScreenDerivationTick(
        route=route,
        frames_read=len(frames),
        observations_published=published,
        coalesced=coalesced,
        spans=tuple(spans),
    )


__all__ = [
    "ActivitySpan",
    "ContextDimensionConflictError",
    "DECLARED_EGRESS",
    "HOST_LOCAL_VISION_ALLOWLIST_ENV",
    "RawEgressRefusedError",
    "resolve_local_vision_endpoint",
    "DerivationRoute",
    "DerivedActivity",
    "ENGINE_VERSION",
    "LOCAL_VISION_MODEL",
    "LOCAL_VISION_PROVIDER",
    "LocalVisionUnavailableError",
    "PaidRouteRejectedError",
    "READER_ID",
    "SPAN_DIMENSIONS",
    "STAGE_NAME",
    "ScreenDerivationTick",
    "ScreenFrame",
    "ScreenFrameUndecodableError",
    "TASK_KIND",
    "UnprovenancedObservationError",
    "VisionRequest",
    "derive_activity_observations",
    "resolve_derivation_route",
    "screen_frame_from_raw_record",
]
