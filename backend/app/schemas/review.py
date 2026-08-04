"""审图相关 schema（P0 占位，字段将在 Task 4 完善）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReviewCreateRequest(BaseModel):
    """提交审图任务请求。

    review_mode 由系统根据 file_type 与 provider 可用性自动决定，不由客户端指定：
    - image/pdf → vlm（图片/PDF 直接走 VLM OCR）
    - dxf/dwg → vlm / vector_only（矢量解析后渲染图片走 VLM，或矢量级降级）
    - sldprt/sldasm → vlm（提取预览图后走 VLM）
    - step/iges → vlm（3D 渲染等轴侧视图后走 VLM）

    各文件类型所需依赖：
    - image: 无额外依赖
    - pdf: pypdfium2（必装）
    - dxf: ezdxf（已装）
    - dwg: ODA File Converter（外部二进制，需用户预装）
    - sldprt/sldasm: SolidWorks DocMgr API / Shell Thumbnail / SolidWorks（三级降级）
    - step/iges: cadquery-ocp（已装）/ trimesh+pyrender（降级）
    """

    file_key: str = Field(..., description="MinIO 中已上传文件的 key")
    file_type: Literal["sldprt", "sldasm", "dwg", "dxf", "pdf", "image", "step", "iges"] = Field(
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
