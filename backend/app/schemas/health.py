"""健康检查相关 schema。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """存活探针响应。仅表明进程在跑。

    split-llm-vlm-config：分别暴露 LLM 与 VLM 的 provider 名称与可用性，
    便于前端设置页与运维监控独立感知两者状态。``vlm_provider`` 为空串表示
    未配置视觉模型（``get_vlm_provider()`` 返回 None）。
    """

    status: Literal["ok"] = "ok"
    service: str
    version: str
    # LLM（文本模型）状态
    llm_provider: str = ""
    llm_available: bool = False
    # VLM（视觉模型）状态：vlm_provider 空串表示未配置
    vlm_provider: str = ""
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
