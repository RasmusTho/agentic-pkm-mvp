"""The open extraction registry (KA-04): `normalized` → `extracted` (KA-05 candidate).

Implements `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md` § Extraction registry
and `docs/KNOWLEDGE_ACQUISITION/EXTRACTION_REGISTRY_AND_SUMMARY_EXTRACTOR.md`: an extractor is a
registered unit — `(extractor_id, version, input content type, output schema, model identity)` —
and the registry is **open by design**: adding an extractor touches nothing else. This module owns
the registration mechanism and the call site the pipeline will use once wired
(KA-05 #2800 / KA-06 #2801); `app/knowledge_acquisition/extractors/` holds the extractors
themselves (one, `summary`, in this slice).

Contract points this module is responsible for:

- **Registration without pipeline edits.** `register_extractor()` adds an `ExtractorSpec` to a
  process-local registry; `run_extractor()` / `run_registered_extractor()` is the one production
  call site the pipeline will use, once wired, to invoke *any* registered extractor by id — the
  pipeline will never need to import a specific extractor module.
- **Lineage.** Every successful run returns an `ExtractionResult` stamping
  `extractor_id`, `extractor_version`, `model_identity` (`{provider, model}` from the resolved
  `LLMRoute` — the fabric's existing model-identity shape, `app/components/llm/router.py`), the
  upstream `source_content_identity`, and a timestamp — per `REFINEMENT_PIPELINE_CONTRACT.md`
  § Lineage and replay ("stage + stage version + (for extractors) model identity").
- **Idempotent version semantics.** Re-running the same extractor id + version over an unchanged
  `source_content_identity` is a no-op: the prior `ExtractionResult` is returned unchanged, the
  extractor's `run()` is not invoked again. A different (bumped) version for the same source
  content identity always runs and replaces — the newer result becomes the retrievable result for
  that (source_content_identity, extractor_id) pair, per REFINEMENT_PIPELINE_CONTRACT's
  "bumped version replaces" replay invariant. Idempotency/replacement state lives in-process
  (`_RESULTS` keyed by `(source_content_identity, extractor_id, version)`); this slice does not
  persist extraction artifacts (see module docstring note below on scope).
- **Fail-loud, item-scoped failure.** An extractor's `run()` raising is never swallowed: the
  registry lets the exception propagate to the caller (item-scoped per
  REFINEMENT_PIPELINE_CONTRACT § Stage execution model — "loud and item-scoped: it dead-letters
  that item at that stage without blocking other items or other extractors"). No extraction
  artifact is recorded for a failed run, so a subsequent call is *not* treated as an idempotent
  no-op of a nonexistent success.

**Scope note (persistence):** the task spec and `REFINEMENT_PIPELINE_CONTRACT.md` describe
`extracted` as a refinement *level* but do not require this slice to persist extraction artifacts
durably — `candidate` assembly/writeback is KA-05's contract. Per the narrower-reading instruction
for ambiguous persistence scope, this registry keeps extraction results in an in-process cache
(mirroring `normalize()`'s KA-03 precedent of a pure/non-persisting stage) rather than writing to
`app.objects`. If KA-05 needs extraction artifacts to be durable ahead of candidate assembly, that
is this doc's scope question to resolve, not an invention here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol

STAGE_NAME = "extracted"


class ExtractionError(RuntimeError):
    """Item-scoped, loud failure from running a registered extractor.

    Wraps the extractor's own failure (e.g. `ConstrainedCompletionError` from a schema-mismatched
    LLM completion) without producing an extraction artifact. Never swallowed by the registry.
    """

    def __init__(self, *, extractor_id: str, version: int, reason: str) -> None:
        super().__init__(
            f"extraction failed for {extractor_id}@{version}: {reason}"
        )
        self.extractor_id = extractor_id
        self.version = version
        self.reason = reason


class UnknownExtractorError(LookupError):
    """A caller asked to run an `extractor_id` that was never registered."""


class ExtractorRunFn(Protocol):
    """An extractor's run callable: normalized artifact dict -> output payload dict.

    Extractors depend only on the normalized artifact and are mutually independent
    (`REFINEMENT_PIPELINE_CONTRACT.md` § Stage execution model). Any exception raised here
    propagates as-is up through `run_extractor` — the registry does not interpret extractor
    internals, only wraps the outcome in `ExtractionResult` / re-raises as `ExtractionError`.
    """

    def __call__(self, normalized: Mapping[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ExtractorSpec:
    """A registered extractor: `(extractor_id, version, input type, output schema, model identity)`.

    `output_schema_ref` names the schema the extractor's output validates against (registered via
    `app.components.llm.constrained.register_schema` by the extractor module itself — this
    registry does not own schema validation, the extractor's own `run()` does, consistent with
    `constrained_completion`'s existing typed-LLM-boundary seam). `input_content_type` documents
    which normalized content type the extractor consumes (e.g. `"transcript"`). It is
    **advisory-only by design**
    (`docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md` § Extraction registry): the
    registry does not validate it against the normalized payload, because the current
    `normalized` shape (`NormalizedTranscript.as_dict()`) carries no content-type discriminator
    to check it against — one normalized shape (transcripts) exists today, so there is nothing to
    mismatch. Each extractor's own `run()` remains the fail-loud boundary for a payload it cannot
    use.
    """

    extractor_id: str
    version: int
    input_content_type: str
    output_schema_ref: str
    run: ExtractorRunFn
    model_identity: Callable[[], dict[str, str]] | None = None


@dataclass(frozen=True)
class ExtractionResult:
    """Lineage-stamped output of one extractor run.

    `source_content_identity` ties the result back to the `raw` record's identity (propagated
    through `normalized["source_content_identity"]`, per `NormalizedTranscript.as_dict()`);
    `extractor_id` + `extractor_version` + `model_identity` are the lineage triple
    `REFINEMENT_PIPELINE_CONTRACT.md` § Lineage and replay requires for every derived artifact.
    """

    extractor_id: str
    extractor_version: int
    source_content_identity: str
    output: dict[str, Any]
    model_identity: dict[str, str]
    stage: str = STAGE_NAME
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    replayed: bool = False
    """True when this result was returned from the idempotent-no-op cache rather than a fresh run."""

    def as_dict(self) -> dict[str, Any]:
        """Deterministic, JSON-serializable projection (dict/list/str/float/bool/None only)."""
        return {
            "stage": self.stage,
            "extractor_id": self.extractor_id,
            "extractor_version": self.extractor_version,
            "source_content_identity": self.source_content_identity,
            "model_identity": dict(self.model_identity),
            "output": dict(self.output),
            "created_at": self.created_at.isoformat(),
            "replayed": self.replayed,
        }


_REGISTRY: dict[str, ExtractorSpec] = {}
# Idempotency/replacement cache: (source_content_identity, extractor_id) -> (version, result).
# A lookup only hits the no-op path when the cached version equals the requested version; any
# other version (bumped or otherwise) runs fresh and replaces the cache entry, per
# REFINEMENT_PIPELINE_CONTRACT's "bumped version replaces" invariant.
_RESULTS: dict[tuple[str, str], tuple[int, ExtractionResult]] = {}


def register_extractor(spec: ExtractorSpec) -> None:
    """Register `spec` under its `extractor_id`. Registering the same id again replaces the spec
    (e.g. a version bump for the same extractor) — this is the only place a new extractor id is
    introduced; the call site the pipeline will use once wired (`run_extractor`) will not need to
    change.
    """
    _REGISTRY[spec.extractor_id] = spec


def registered_extractor(extractor_id: str) -> ExtractorSpec:
    spec = _REGISTRY.get(extractor_id)
    if spec is None:
        raise UnknownExtractorError(f"no extractor registered under id {extractor_id!r}")
    return spec


def registered_extractor_ids() -> tuple[str, ...]:
    """All currently registered extractor ids (registry introspection, e.g. for a pipeline fan-out)."""
    return tuple(_REGISTRY.keys())


def clear_registry() -> None:
    """Test-only: reset the process-local registry and result cache between test modules."""
    _REGISTRY.clear()
    _RESULTS.clear()


def clear_extraction_results() -> None:
    """Drop every cached extraction result while keeping extractors registered.

    The replay path's "delete every derived level" hook for the `extracted`
    level (KA-06 #2801, `REFINEMENT_PIPELINE_CONTRACT.md` § Lineage and
    replay): extraction artifacts are not durably persisted in this slice
    (see module docstring scope note), so the in-process result cache IS the
    derived level, and clearing it forces a genuine fresh re-run on the next
    `run_extractor` call. Registered extractor specs are deliberately left
    untouched — replay re-runs the registered pipeline, it does not
    de-register it.
    """
    _RESULTS.clear()


def run_extractor(extractor_id: str, normalized: Mapping[str, Any]) -> ExtractionResult:
    """Run the extractor registered under `extractor_id` against a `normalized` artifact.

    This is the **one production call site** the pipeline will use, once wired, to run any
    registered extractor — adding extractor #2 means one `register_extractor()` call in a new
    module, never a change here (`REFINEMENT_PIPELINE_CONTRACT.md` § Extraction registry:
    "Adding one MUST NOT require touching this contract, other extractors, or any source
    plugin").

    Idempotent no-op: if the same `(source_content_identity, extractor_id)` pair already has a
    cached result at the *same* `spec.version`, that cached result is returned unchanged
    (`replayed=True`) and the extractor's `run()` is not invoked again. A different version always
    runs fresh and replaces the cache entry.

    Raises `UnknownExtractorError` if `extractor_id` was never registered, or `ExtractionError`
    (item-scoped, loud) if the extractor's `run()` raises — no extraction artifact is produced or
    cached for a failed run.
    """
    spec = registered_extractor(extractor_id)

    source_content_identity = normalized.get("source_content_identity")
    if not source_content_identity or not isinstance(source_content_identity, str):
        raise ExtractionError(
            extractor_id=extractor_id,
            version=spec.version,
            reason="normalized artifact is missing a string source_content_identity",
        )

    cache_key = (source_content_identity, extractor_id)
    cached = _RESULTS.get(cache_key)
    if cached is not None and cached[0] == spec.version:
        _, prior_result = cached
        return ExtractionResult(
            extractor_id=prior_result.extractor_id,
            extractor_version=prior_result.extractor_version,
            source_content_identity=prior_result.source_content_identity,
            output=dict(prior_result.output),
            model_identity=dict(prior_result.model_identity),
            created_at=prior_result.created_at,
            replayed=True,
        )

    try:
        output = spec.run(normalized)
    except Exception as exc:  # noqa: BLE001 - re-raised as the typed, item-scoped failure below
        raise ExtractionError(
            extractor_id=extractor_id, version=spec.version, reason=str(exc)
        ) from exc

    model_identity = spec.model_identity() if spec.model_identity is not None else {}
    result = ExtractionResult(
        extractor_id=spec.extractor_id,
        extractor_version=spec.version,
        source_content_identity=source_content_identity,
        output=output,
        model_identity=dict(model_identity),
        replayed=False,
    )
    _RESULTS[cache_key] = (spec.version, result)
    return result


__all__ = [
    "STAGE_NAME",
    "ExtractionError",
    "ExtractionResult",
    "ExtractorRunFn",
    "ExtractorSpec",
    "UnknownExtractorError",
    "clear_extraction_results",
    "clear_registry",
    "register_extractor",
    "registered_extractor",
    "registered_extractor_ids",
    "run_extractor",
]
