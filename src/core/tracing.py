"""OpenTelemetry tracing setup.

See docs/architecture/02-foundation.md Section 4.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from src.core.config import TracingSettings


def setup_tracing(settings: TracingSettings) -> TracerProvider | None:
    """Initialize OpenTelemetry tracing. Returns provider or None if disabled."""
    if not settings.enabled:
        return None

    resource = Resource.create(
        {
            "service.name": settings.service_name,
        }
    )

    provider = TracerProvider(resource=resource)

    if settings.exporter == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=settings.otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except ImportError:
            # Fallback to console if OTLP not available
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif settings.exporter == "console":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    # else: "none" — no exporter

    trace.set_tracer_provider(provider)
    return provider


def get_tracer(name: str = "agent-platform") -> trace.Tracer:
    """Get a tracer instance."""
    return trace.get_tracer(name)
