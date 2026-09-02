# neurosurfer/tracing/__init__.py
from .models import TraceResult, TraceStep
from .span import (
    ConsoleTracer,
    LoggerTracer,
    MemorySpanTracer,
    NullSpanTracer,
    RichTracer,  # RichTracer becomes ConsoleTracer if `rich` package is missing
    SpanTracer,
)
from .tracer import Tracer, TracerConfig, TraceStepContext

__all__ = [
    "SpanTracer",
    "ConsoleTracer",
    "LoggerTracer",
    "MemorySpanTracer",
    "NullSpanTracer",
    "RichTracer",
    "TraceStep",
    "TraceResult",
    "Tracer",
    "TracerConfig",
    "TraceStepContext",
]
