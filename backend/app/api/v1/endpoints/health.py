"""健康检查端点：/healthz（存活）+ /readyz（就绪）。

遵循"以主动测试为荣"原则：/readyz 实际探测各依赖组件。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.api.deps import SettingsDep
from app.config import Settings
from app.database import check_db_connected
from app.logging import get_logger
from app.schemas.health import (
    HealthResponse,
    ReadinessComponent,
    ReadinessResponse,
)
from app.services.redis_probe import check_redis_connected

router = APIRouter()
log = get_logger(__name__)


@router.get(
    "/healthz",
    response_model=HealthResponse,
    summary="存活探针",
    description="表明进程在运行。不检查依赖，但会附带当前 LLM provider 的可用性快照。",
)
async def healthz(settings: Settings = SettingsDep) -> HealthResponse:
    # SubTask 3.6：暴露当前 LLM provider 与可用性。
    # 延迟 import 避免启动时初始化 provider（provider 初始化会探测远端，可能阻塞）。
    # 同步 provider 方法通过 to_thread 放到线程池，避免阻塞事件循环；
    # 任何异常都降级为 False，不让 healthz 抛 500。
    provider_name = settings.LLM_PROVIDER
    llm_available = False
    vlm_available = False
    try:
        from app.services.ai import get_llm_provider

        provider = get_llm_provider()
        llm_available = await asyncio.wait_for(
            asyncio.to_thread(provider.is_available), timeout=5.0
        )
        vlm_available = await asyncio.wait_for(
            asyncio.to_thread(provider.is_vlm_available), timeout=5.0
        )
    except asyncio.TimeoutError:
        log.warning("healthz.provider_probe_timeout", provider=provider_name)
    except Exception as e:  # noqa: BLE001
        log.warning("healthz.provider_probe_failed", provider=provider_name, error=str(e))

    return HealthResponse(
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
        llm_provider=provider_name,
        llm_available=llm_available,
        vlm_available=vlm_available,
    )


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    summary="就绪探针",
    description="探测 PostgreSQL / Redis 等关键依赖；任一不可用则返回 503。",
)
async def readyz(settings: Settings = SettingsDep) -> JSONResponse:
    components: list[ReadinessComponent] = []

    # PostgreSQL
    try:
        pg_ok = await asyncio.wait_for(check_db_connected(), timeout=3.0)
    except asyncio.TimeoutError:
        pg_ok = False
    except Exception:  # noqa: BLE001
        pg_ok = False
    components.append(
        ReadinessComponent(
            name="postgres",
            status="ok" if pg_ok else "down",
            detail=None if pg_ok else "connection failed or timed out",
        )
    )

    # Redis（同步探测，通过 to_thread 避免阻塞事件循环）
    try:
        rd_ok = await asyncio.wait_for(
            asyncio.to_thread(check_redis_connected), timeout=3.0
        )
    except asyncio.TimeoutError:
        rd_ok = False
    except Exception:  # noqa: BLE001
        rd_ok = False
    components.append(
        ReadinessComponent(
            name="redis",
            status="ok" if rd_ok else "down",
            detail=None if rd_ok else "connection failed or timed out",
        )
    )

    all_ok = all(c.status == "ok" for c in components)
    overall = "ok" if all_ok else "down"
    http_status = (
        status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    log.info("readyz.probed", overall=overall, components=[c.model_dump() for c in components])

    return JSONResponse(
        status_code=http_status,
        content=ReadinessResponse(
            status=overall,
            service=settings.APP_NAME,
            version=settings.APP_VERSION,
            components=components,
        ).model_dump(),
    )
