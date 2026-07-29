"""OpenTelemetry tracing 配置。

遵循"以复用现有为荣"原则，使用官方 instrumentation 包，
不手写中间件。OTEL_ENABLED=false 时为空操作，避免开发环境依赖 collector。
"""

from __future__ import annotations

from typing import Optional

from app.config import settings
from app.logging import get_logger

log = get_logger(__name__)

_tracer_provider: Optional[object] = None


def configure_tracing() -> None:
    """初始化 OpenTelemetry SDK + FastAPI/Celery 自动埋点。

    当 OTEL_ENABLED=false 或未配置 endpoint 时，跳过初始化。
    """
    global _tracer_provider

    if not settings.OTEL_ENABLED:
        log.info("tracing.disabled", reason="OTEL_ENABLED=false")
        return

    if not settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        log.warning("tracing.disabled", reason="OTEL_EXPORTER_OTLP_ENDPOINT empty")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        resource = Resource.create(
            {"service.name": settings.OTEL_SERVICE_NAME}
        )
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(
            endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer_provider = provider

        log.info(
            "tracing.initialized",
            service=settings.OTEL_SERVICE_NAME,
            endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        )
    except ImportError as e:
        log.warning("tracing.deps_missing", error=str(e))
    except Exception as e:  # noqa: BLE001
        log.error("tracing.init_failed", error=str(e))


def instrument_fastapi(app) -> None:
    """对 FastAPI 应用注入自动埋点。在 main.py 创建 app 后调用。"""
    if _tracer_provider is None:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        log.info("tracing.fastapi_instrumented")
    except ImportError:
        pass


def instrument_celery() -> None:
    """对 Celery 应用注入自动埋点。在 celery_app.py 创建后调用。"""
    if _tracer_provider is None:
        return
    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        CeleryInstrumentor.instrument()
        log.info("tracing.celery_instrumented")
    except ImportError:
        pass
