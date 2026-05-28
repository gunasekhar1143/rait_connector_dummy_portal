"""OpenTelemetry setup for the Dummy Portal.

Configures a TracerProvider with ConsoleSpanExporter (PoC default).
Gracefully no-ops if opentelemetry packages are not installed.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, BatchSpanProcessor, SimpleSpanProcessor
    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False

_tracer: object = None


def setup_otel(service_name: str = "rait-dummy-portal", exporter: str = "console") -> None:
    global _tracer
    if not _OTEL_AVAILABLE:
        logger.warning("opentelemetry-sdk not installed — tracing disabled")
        return

    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)

    if exporter == "console":
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
    else:
        processor = SimpleSpanProcessor(ConsoleSpanExporter())   # fallback

    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)
    logger.info("OpenTelemetry tracing enabled (exporter=%s)", exporter)


def get_tracer():
    if not _OTEL_AVAILABLE or _tracer is None:
        return _NullTracer()
    from opentelemetry import trace
    return trace.get_tracer("rait-dummy-portal")


class _NullSpan:
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def set_attribute(self, *_): pass
    def record_exception(self, *_): pass
    def set_status(self, *_): pass


class _NullTracer:
    def start_as_current_span(self, name, **kwargs):
        return _NullSpan()
