"""OpenTelemetry 全链路 tracing 扩展（SubTask 16.1）。

复用既有 ``app/tracing.py`` 的 TracerProvider 初始化逻辑，
在其基础上扩展：
- httpx / requests 客户端自动埋点（HTTPXClientInstrumentor / RequestsInstrumentor）
- 关键业务 span 工具：审图流程 / 生成流程 / SolidWorks 调用 / RAG 检索

遵循"以谨慎重构为荣"原则：不修改 ``app/tracing.py`` 既有函数签名，
仅在本模块新增扩展能力。``OTEL_ENABLED=false`` 时所有操作降级为空操作，
``opentelemetry-instrumentation-httpx/requests`` 未安装时优雅降级。
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator, Optional

from app.config import settings
from app.logging import get_logger

log = get_logger(__name__)

# 复用 app.tracing 的 provider 状态（同一进程内共享）
# 注意：不能 `from app.tracing import _tracer_provider`，那是值拷贝；
# 必须动态读取 app.tracing._tracer_provider 才能拿到 configure_tracing() 后的最新值。
from app import tracing as _base_tracing  # noqa: E402
from app.tracing import (  # noqa: E402  复用既有函数
    configure_tracing,
    instrument_celery,
    instrument_fastapi,
)


def _provider_active() -> bool:
    """动态读取 app.tracing 的 provider 状态（避免值拷贝陷阱）。"""
    return getattr(_base_tracing, "_tracer_provider", None) is not None


_httpx_instrumented: bool = False
_requests_instrumented: bool = False


def instrument_httpx() -> bool:
    """对 httpx 客户端注入自动埋点。

    Returns:
        True 表示已成功埋点；False 表示未启用或依赖缺失。
    """
    global _httpx_instrumented
    if _httpx_instrumented:
        return True
    if not _provider_active():
        return False
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
        _httpx_instrumented = True
        log.info("tracing.httpx_instrumented")
        return True
    except ImportError:
        log.warning("tracing.httpx.deps_missing")
        return False
    except Exception as e:  # noqa: BLE001
        log.warning("tracing.httpx.instrument_failed", error=str(e))
        return False


def instrument_requests() -> bool:
    """对 requests 客户端注入自动埋点。

    Returns:
        True 表示已成功埋点；False 表示未启用或依赖缺失。
    """
    global _requests_instrumented
    if _requests_instrumented:
        return True
    if not _provider_active():
        return False
    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor

        RequestsInstrumentor().instrument()
        _requests_instrumented = True
        log.info("tracing.requests_instrumented")
        return True
    except ImportError:
        log.warning("tracing.requests.deps_missing")
        return False
    except Exception as e:  # noqa: BLE001
        log.warning("tracing.requests.instrument_failed", error=str(e))
        return False


def instrument_all_http_clients() -> dict[str, bool]:
    """一次性对 httpx + requests 客户端注入埋点。

    Returns:
        各客户端埋点结果，例如 ``{"httpx": True, "requests": False}``。
    """
    return {
        "httpx": instrument_httpx(),
        "requests": instrument_requests(),
    }


def get_tracer(name: str = settings.OTEL_SERVICE_NAME) -> Any:
    """获取业务 tracer。

    OTEL 未启用时返回 None，调用方应使用 ``trace_span`` 上下文管理器降级。
    """
    if not _provider_active():
        return None
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except Exception:  # noqa: BLE001
        return None


@contextlib.contextmanager
def trace_span(name: str, attributes: Optional[dict[str, Any]] = None) -> Iterator[Optional[Any]]:
    """业务 span 上下文管理器。

    用法：
        with trace_span("review.pipeline", {"file_type": "dxf"}) as span:
            ...

    OTEL 未启用时为空操作上下文（yield None），调用方无需条件分支。
    """
    tracer = get_tracer()
    if tracer is None:
        yield None
        return
    try:
        with tracer.start_as_current_span(name) as span:
            if attributes and span is not None:
                for k, v in attributes.items():
                    try:
                        span.set_attribute(k, v)
                    except Exception:  # noqa: BLE001  属性设置失败不阻断业务
                        pass
            yield span
    except Exception as e:  # noqa: BLE001  tracing 异常不影响业务
        log.debug("tracing.span.failed", name=name, error=str(e))
        yield None


# ===== 关键业务 span 快捷入口（语义化命名）=====


def review_pipeline_span(file_type: str = "", file_key: str = ""):
    """审图流程 span。"""
    attrs: dict[str, Any] = {"pipeline": "review"}
    if file_type:
        attrs["review.file_type"] = file_type
    if file_key:
        attrs["review.file_key"] = file_key
    return trace_span("review.pipeline", attrs)


def generation_pipeline_span(intent: str = ""):
    """生成流程 span。"""
    attrs: dict[str, Any] = {"pipeline": "generation"}
    if intent:
        attrs["generation.intent"] = intent
    return trace_span("generation.pipeline", attrs)


def solidworks_call_span(operation: str = ""):
    """SolidWorks 调用 span。"""
    attrs: dict[str, Any] = {"system": "solidworks"}
    if operation:
        attrs["solidworks.operation"] = operation
    return trace_span("solidworks.call", attrs)


def rag_retrieval_span(query: str = "", top_k: int = 0):
    """RAG 检索 span。"""
    attrs: dict[str, Any] = {"pipeline": "rag"}
    if query:
        attrs["rag.query"] = query[:200]  # 截断避免超大属性
    if top_k:
        attrs["rag.top_k"] = top_k
    return trace_span("rag.retrieval", attrs)


def configure_full_tracing() -> dict[str, bool]:
    """一次性配置全部 tracing：FastAPI / Celery / httpx / requests。

    在 main.py / celery_app.py 中调用 ``configure_tracing()`` 之后调用本函数，
    可一次性完成所有客户端埋点。

    Returns:
        各组件埋点状态。
    """
    # 确保基础 provider 已初始化（幂等）
    configure_tracing()
    result: dict[str, bool] = {
        "tracer_provider": _provider_active(),
        "httpx": instrument_httpx(),
        "requests": instrument_requests(),
    }
    log.info("tracing.full_configured", **result)
    return result


def self_test() -> dict[str, Any]:
    """self_test：验证 tracing 模块在 OTEL_ENABLED=False 时降级正常。

    遵循现有模块 self_test 风格：返回结果字典，不抛异常。
    """
    result: dict[str, Any] = {
        "otel_enabled": settings.OTEL_ENABLED,
        "service_name": settings.OTEL_SERVICE_NAME,
        "endpoint": settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        "tracer_provider_active": _provider_active(),
        "httpx_instrumented": _httpx_instrumented,
        "requests_instrumented": _requests_instrumented,
        "span_degraded_ok": False,
    }

    # 验证 trace_span 在未启用时降级为空操作
    try:
        with trace_span("self_test.span") as span:
            result["span_degraded_ok"] = span is None  # OTEL 关闭时 span 应为 None
    except Exception as e:  # noqa: BLE001
        result["span_degraded_error"] = str(e)

    # 验证业务 span 工厂不抛异常
    for factory_name, factory in (
        ("review_pipeline_span", lambda: review_pipeline_span("dxf", "k1")),
        ("generation_pipeline_span", lambda: generation_pipeline_span("bolt")),
        ("solidworks_call_span", lambda: solidworks_call_span("extrude")),
        ("rag_retrieval_span", lambda: rag_retrieval_span("GB/T 1182", 5)),
    ):
        try:
            with factory() as span:
                pass
            result[f"{factory_name}_ok"] = True
        except Exception as e:  # noqa: BLE001
            result[f"{factory_name}_ok"] = False
            result[f"{factory_name}_error"] = str(e)

    return result


if __name__ == "__main__":
    import json

    print(json.dumps(self_test(), indent=2, ensure_ascii=False, default=str))
