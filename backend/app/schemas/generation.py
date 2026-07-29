"""生成相关 schema（P0 占位，字段将在 Task 5 完善）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GenerationCreateRequest(BaseModel):
    """提交生成任务请求。"""

    input_type: Literal["text", "sketch"] = Field(..., description="输入类型")
    prompt: str | None = Field(None, description="自然语言描述（input_type=text 时必填）")
    sketch_key: str | None = Field(
        None, description="MinIO 中已上传草图的 key（input_type=sketch 时必填）"
    )
    output_format: Literal["step", "iges", "stl", "dxf"] = Field(
        "step", description="期望输出格式"
    )


class GenerationTaskAccepted(BaseModel):
    """生成任务受理响应。"""

    task_id: str
    status: Literal["queued"] = "queued"
    websocket_url: str
