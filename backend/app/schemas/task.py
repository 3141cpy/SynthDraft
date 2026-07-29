"""通用任务状态 schema。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class TaskStatusResponse(BaseModel):
    """查询任务状态响应。"""

    task_id: str
    status: Literal["queued", "running", "succeeded", "failed", "canceled"]
    progress: int = 0
    result: dict | None = None
    error: str | None = None
