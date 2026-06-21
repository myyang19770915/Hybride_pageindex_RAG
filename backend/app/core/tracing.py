import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_initialized = False
_tracer: Any | None = None


def configure_tracing() -> bool:
    """Configure OpenTelemetry export to Phoenix when an endpoint is set.

    Safe to call repeatedly and on systems without OpenTelemetry installed or
    without a configured endpoint: it becomes a no-op and the span helpers below
    degrade to plain pass-throughs.
    """
    global _initialized, _tracer
    if _initialized:
        return _tracer is not None
    _initialized = True

    settings = get_settings()
    if not settings.phoenix_endpoint:
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": settings.phoenix_project,
                # Phoenix groups traces by this attribute.
                "openinference.project.name": settings.phoenix_project,
            }
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.phoenix_endpoint))
        )
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("hybride-pageindex-rag")
        _instrument_agno(provider)
        logger.info("OpenTelemetry tracing enabled -> %s", settings.phoenix_endpoint)
        return True
    except Exception:
        logger.exception("Failed to configure OpenTelemetry tracing; continuing without export.")
        _tracer = None
        return False


def _instrument_agno(provider: Any) -> None:
    """Enable OpenInference auto-instrumentation for the Agno agent runtime.

    Optional: when the instrumentor is not installed, the manual spans emitted by
    the retrieval pipeline still export. This only adds richer LLM/agent spans.
    """
    try:
        from openinference.instrumentation.agno import AgnoInstrumentor

        AgnoInstrumentor().instrument(tracer_provider=provider)
        logger.info("OpenInference Agno instrumentation enabled.")
    except Exception:
        logger.debug("OpenInference Agno instrumentation unavailable; skipping.", exc_info=True)


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    if _tracer is None:
        yield None
        return
    # Use a manual span (not set_as_current) so it is safe to hold open across
    # generator ``yield`` boundaries — making it "current" would attach an OTel
    # context that cannot be detached in the resumed generator context.
    otel_span = _tracer.start_span(name)
    for key, value in (attributes or {}).items():
        otel_span.set_attribute(key, value)
    try:
        yield otel_span
    finally:
        otel_span.end()


def add_event(name: str, attributes: dict[str, Any] | None = None) -> None:
    if _tracer is None:
        return
    from opentelemetry import trace

    current_span = trace.get_current_span()
    if current_span is not None:
        current_span.add_event(name, attributes or {})
