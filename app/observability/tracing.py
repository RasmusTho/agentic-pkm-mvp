from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from typing import Iterator, Optional

from app.config.paths import resolve_system_settings_path

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    _OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - best effort optional dependency
    # Intentionally silent optional-import guard: opentelemetry is not a
    # required dependency; tracing degrades to no-ops when it is absent.
    _OTEL_AVAILABLE = False
    trace = None  # type: ignore


def _settings_path() -> Optional[Path]:
    try:
        return resolve_system_settings_path()
    except Exception:
        # Intentional swallow: no resolvable settings path means tracing stays
        # disabled — logged so a misconfigured vault root is not invisible.
        logger.warning("Could not resolve system settings path for tracing", exc_info=True)
        return None


def _read_settings() -> dict:
    try:
        import yaml  # local import keeps dependency optional

        path = _settings_path()
        if path and path.exists():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        # Intentional swallow: unreadable/invalid settings disable tracing
        # rather than break startup — but never silently (#3894).
        logger.warning("Failed to read tracing settings; tracing stays disabled", exc_info=True)
    return {}


def start_tracer(service_name: str = "promotion-agent") -> None:
    if not _OTEL_AVAILABLE:
        return

    settings = _read_settings()
    runtime = (settings.get("runtime") or {})
    observability = (settings.get("observability") or {})

    if not bool(runtime.get("enable_tracing")):
        return

    endpoint = os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT", observability.get("otlp_endpoint") or "http://localhost:4317"
    )
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)


@contextlib.contextmanager
def span(name: str) -> Iterator[object]:
    if _OTEL_AVAILABLE and trace.get_tracer_provider() is not None:
        tracer = trace.get_tracer("app")
        with tracer.start_as_current_span(name) as sp:
            yield sp
    else:
        yield None


def current_trace_id() -> Optional[str]:
    if not _OTEL_AVAILABLE:
        return None
    try:
        span_obj = trace.get_current_span()
        ctx = span_obj.get_span_context()
        if ctx and ctx.is_valid:
            return f"{ctx.trace_id:032x}"
    except Exception:
        # Intentional swallow on a hot path: this is called for every event
        # append, so log at DEBUG (with traceback) to avoid log spam while
        # keeping the failure observable when debugging tracing issues.
        logger.debug("Failed to read current trace id", exc_info=True)
    return None
