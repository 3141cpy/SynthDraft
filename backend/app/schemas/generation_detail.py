"""生成模块详细 schema（Task 5）。

包含执行结果、几何校验、生成请求/结果等结构化数据模型。
与 ``app.schemas.generation``（API 受理层）解耦：
- generation.py：HTTP 受理层（GenerationCreateRequest / GenerationTaskAccepted）
- generation_detail.py：管线内部产物（ExecutionResult / GeometryValidation / GenerationResult）

设计原则：
- 所有路径字段统一存字符串（pydantic 序列化友好），原始 Path 由调用方包装。
- 失败时也要返回结构化结果，便于前端展示与日志归因。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ===== 执行结果 =====


class ExecutionResult(BaseModel):
    """CadQuery 代码沙箱执行结果。

    Attributes:
        success: 是否成功执行并产出预期文件
        stdout: 子进程标准输出（截断后）
        stderr: 子进程标准错误（截断后）
        output_files: 实际产出的文件绝对路径列表
        elapsed_ms: 执行耗时（毫秒）
        exit_code: 子进程退出码（未执行时为 None）
        violations: 静态扫描发现的危险 import 列表（拒绝执行时非空）
    """

    success: bool = Field(..., description="是否成功执行")
    stdout: str = Field(default="", description="子进程标准输出")
    stderr: str = Field(default="", description="子进程标准错误")
    output_files: list[str] = Field(default_factory=list, description="产出文件绝对路径")
    elapsed_ms: int = Field(default=0, description="执行耗时（毫秒）")
    exit_code: int | None = Field(default=None, description="子进程退出码")
    violations: list[str] = Field(
        default_factory=list, description="静态扫描违规列表（拒绝执行时非空）"
    )


# ===== 几何校验 =====


class GeometryValidation(BaseModel):
    """STEP 文件几何校验结果。

    Attributes:
        is_valid: 是否通过校验（体积>0、包围盒在合理范围、无自相交）
        volume: 体积（mm³，与 STEP 单位一致）
        bounding_box: (xmin, ymin, zmin, xmax, ymax, zmax) 六元组
        surface_area: 表面积（mm²）
        errors: 校验失败原因列表（is_valid=False 时非空）
        backend: 校验引擎后端（"OCP"/"OCC"），不可用时为 None
    """

    is_valid: bool = Field(..., description="是否通过几何校验")
    volume: float = Field(default=0.0, description="体积 mm³")
    bounding_box: tuple[float, float, float, float, float, float] | None = Field(
        default=None, description="(xmin,ymin,zmin,xmax,ymax,zmax)"
    )
    surface_area: float = Field(default=0.0, description="表面积 mm²")
    errors: list[str] = Field(default_factory=list, description="校验失败原因")
    backend: str | None = Field(default=None, description="OCC 后端标识")


# ===== 生成请求/结果 =====


class GenerationRequest(BaseModel):
    """生成任务内部请求模型（HTTP 入参与 Celery 入参的统一中间表示）。

    Attributes:
        input_type: 输入类型（text 自然语言 / sketch 草图）
        prompt: 自然语言描述
        sketch_key: 草图对象 key（MinIO）
        output_format: 期望输出格式（step/stl/dxf/iges）
        history: 多轮对话历史（role/content 列表）
    """

    input_type: Literal["text", "sketch"] = Field(..., description="输入类型")
    prompt: str = Field(default="", description="自然语言描述")
    sketch_key: str | None = Field(default=None, description="草图对象 key")
    output_format: Literal["step", "stl", "dxf", "iges"] = Field(
        "step", description="期望输出格式"
    )
    history: list[dict[str, Any]] = Field(
        default_factory=list, description="多轮对话历史"
    )


class GenerationResult(BaseModel):
    """生成任务最终结果（Celery 任务返回值 / GET 结果端点响应体）。

    Attributes:
        task_id: Celery 任务 ID
        input_prompt: 原始输入 prompt
        generated_code: LLM/模板生成的 CadQuery Python 代码
        execution: 沙箱执行结果
        geometry_validation: 几何校验结果（执行失败或 STEP 缺失时为 None）
        output_files: 产出文件绝对路径列表（与 execution.output_files 同步）
        mode: 生成模式（llm / template）
        metadata: 附加元数据（模型名/耗时/降级原因等）
    """

    task_id: str = Field(..., description="Celery 任务 ID")
    input_prompt: str = Field(default="", description="原始输入 prompt")
    generated_code: str = Field(default="", description="生成的 CadQuery 代码")
    execution: ExecutionResult = Field(
        default_factory=lambda: ExecutionResult(success=False),
        description="沙箱执行结果",
    )
    geometry_validation: GeometryValidation | None = Field(
        default=None, description="几何校验结果"
    )
    output_files: list[str] = Field(default_factory=list, description="产出文件路径")
    mode: Literal["llm", "template"] = Field(
        "template", description="生成模式（llm 模板）"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="附加元数据"
    )


# ===== 同步执行请求（POST /generations/execute）=====


class ExecuteCodeRequest(BaseModel):
    """用户编辑后代码的同步执行请求。

    用户在 Monaco Editor 中编辑 CadQuery 代码后，通过此端点同步执行。
    """

    code: str = Field(..., description="用户编辑后的 CadQuery Python 代码")
    output_format: Literal["step", "stl", "dxf", "iges"] = Field(
        "step", description="期望输出格式"
    )
    timeout: int = Field(default=30, ge=1, le=120, description="执行超时秒数")


class ExecuteCodeResponse(BaseModel):
    """同步执行响应（含执行结果 + 几何校验 + 下载链接）。"""

    execution: ExecutionResult
    geometry_validation: GeometryValidation | None = None
    download_urls: list[str] = Field(
        default_factory=list, description="产出文件下载 URL（相对路径）"
    )
