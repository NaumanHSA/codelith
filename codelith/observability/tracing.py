from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from codelith.config import get_settings

_TRACER_NAME = "docany"


def setup_tracing() -> None:
    settings = get_settings()
    if not settings.OTEL_ENABLED:
        return

    provider = TracerProvider()
    if settings.is_production:
        exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


def get_otel_tracer(name: str = _TRACER_NAME) -> trace.Tracer:
    return trace.get_tracer(name)


@contextmanager
def agent_span(
    agent_name: str,
    job_id: int,
    **attributes: Any,
) -> Generator[trace.Span, None, None]:
    """OTEL span wrapping a single agent invocation."""
    tracer = get_otel_tracer()
    with tracer.start_as_current_span(f"agent.{agent_name}") as span:
        span.set_attribute("agent.name", agent_name)
        span.set_attribute("job.id", str(job_id))
        for k, v in attributes.items():
            try:
                span.set_attribute(k, str(v))
            except Exception:
                pass
        try:
            yield span
        except Exception as exc:
            span.set_status(trace.status.StatusCode.ERROR, str(exc))
            raise


@contextmanager
def workflow_span(job_id: int) -> Generator[trace.Span, None, None]:
    """OTEL span wrapping the entire documentation workflow."""
    tracer = get_otel_tracer()
    with tracer.start_as_current_span("workflow.documentation") as span:
        span.set_attribute("job.id", str(job_id))
        try:
            yield span
        except Exception as exc:
            span.set_status(trace.status.StatusCode.ERROR, str(exc))
            raise
