"""健康检查相关 schema。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """存活探针响应。仅表明进程在跑。"""

    status: Literal["ok"] = "ok"
    service: str
    version: str
    # SubTask 3.6：暴露 LLM provider 状态（向后兼容，默认值确保旧客户端不破坏）
    llm_provider: str = ""
    llm_available: bool = False
    vlm_available: bool = False


class ReadinessComponent(BaseModel):
    """就绪探针中各依赖组件的状态。"""

    name: str
    status: Literal["ok", "down"]
    detail: str | None = None


class ReadinessResponse(BaseModel):
    """就绪探针响应。表明所有关键依赖可用。"""

    status: Literal["ok", "degraded", "down"]
    service: str
    version: str
    components: list[ReadinessComponent]
