"""审图相关 schema（P0 占位，字段将在 Task 4 完善）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReviewCreateRequest(BaseModel):
    """提交审图任务请求。"""

    file_key: str = Field(..., description="MinIO 中已上传文件的 key")
    file_type: Literal["sldprt", "sldasm", "dwg", "dxf", "pdf", "image"] = Field(
        ..., description="输入文件类型"
    )
    standard_set: list[str] = Field(
        default_factory=lambda: ["GB/T 1182", "GB/T 4457.4"],
        description="适用的规范集合",
    )


class ReviewTaskAccepted(BaseModel):
    """审图任务受理响应。"""

    task_id: str
    status: Literal["queued"] = "queued"
    websocket_url: str = Field(..., description="订阅任务进度的 WebSocket 路径")
