"""文件上传相关 schema。

P0 阶段：审图与生成模块均需先上传文件获得 file_key，
再调用 /reviews 或 /generations 端点。
file_key 为相对 settings.UPLOAD_DIR 的路径（如 "abc123_零件.dxf"），
后端 Celery 任务通过 _resolve_file_path() 解析为绝对路径。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# 支持的上传文件类型（与 ReviewCreateRequest.file_type / GenerationCreateRequest 对齐）
UploadFileType = Literal["sldprt", "sldasm", "dwg", "dxf", "pdf", "image", "step", "iges"]


class UploadResponse(BaseModel):
    """文件上传响应。"""

    file_key: str = Field(
        ..., description="文件 key（相对 UPLOAD_DIR 的路径），用于后续 /reviews 或 /generations 调用"
    )
    file_name: str = Field(..., description="原始文件名（已净化）")
    file_type: UploadFileType = Field(..., description="推断出的文件类型")
    size: int = Field(..., ge=0, description="文件大小（字节）")
    content_type: str = Field(default="", description="上传时的 Content-Type")


class UploadListResponse(BaseModel):
    """已上传文件列表响应（开发态调试用）。"""

    uploads: list[UploadResponse] = Field(default_factory=list)
    total: int = Field(default=0)
