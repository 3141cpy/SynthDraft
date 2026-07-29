"""审图详细结果 schema（Task 4）。

定义审图管线的核心数据结构：
- ReviewContext：单次审图的输入上下文（CAD 中间表示 + 渲染图片 + 元信息）
- DefectItem：单条缺陷（SubTask 4.5 强制字段：类别/严重等级/坐标/条文引用/修改建议/证据）
- ReviewResult：审图任务最终结果
- SemanticModel：融合矢量+视觉的"几何/拓扑/语义"三层结构化对象（SubTask 4.3）
- ReviewReportData：HTML/PDF 报告模板数据

设计原则：
- 复用 Task 2 的 CADIntermediateModel（组合而非继承）
- 所有字段显式标注 Optional 与默认值，保证向后兼容
- review_mode 字段标注实际使用的审图模式（vlm / vector_only / rule_engine）
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.cad_intermediate import CADIntermediateModel
from app.schemas.precision import PrecisionLevel


# ===== 审图模式 =====
ReviewMode = Literal["vlm", "vector_only", "rule_engine"]


# ===== SubTask 4.1：审图上下文 =====


class ReviewContext(BaseModel):
    """单次审图的输入上下文。

    由 prepare_review_context() 产出，包含解析后的 CAD 中间表示、
    渲染图片路径与解析元信息。
    """

    source_file: str = Field(..., description="源文件绝对路径")
    source_format: Literal["dxf", "dwg", "step", "iges", "unknown"] = Field(
        default="unknown", description="源文件格式"
    )
    cad_model: CADIntermediateModel = Field(
        ..., description="Task 2 解析得到的 CAD 中间表示"
    )
    image_path: str | None = Field(
        default=None, description="DXF 渲染为 PNG 的路径（渲染失败为 None）"
    )
    parse_metadata: dict[str, Any] = Field(
        default_factory=dict, description="解析过程的附加元信息"
    )


# ===== SubTask 4.5：缺陷条目 =====


Severity = Literal["critical", "major", "minor", "warning"]
DefectCategory = Literal[
    "title_block",        # 标题栏
    "layer_naming",       # 图层命名
    "dimensioning",       # 尺寸标注
    "tolerance",          # 形位公差
    "surface_roughness",  # 表面粗糙度
    "line_type",          # 线型
    "view_layout",        # 视图布局
    "text_annotation",    # 文字标注
    "other",
]


class DefectItem(BaseModel):
    """单条缺陷条目（SubTask 4.5 强制字段）。

    所有字段必须显式填充；coordinate 允许 None（无定位的缺陷，
    如"标题栏缺失"这类全局问题）。
    """

    category: DefectCategory = Field(..., description="缺陷类别")
    severity: Severity = Field(..., description="严重等级")
    coordinate: dict[str, float] | None = Field(
        default=None,
        description=(
            "缺陷在图纸中的定位坐标（model space），"
            "如 {'x': 120.5, 'y': 45.0}；无定位时为 None"
        ),
    )
    standard_ref: str = Field(
        ..., description="规范引用文本，如 'GB/T 4457.4-2002 §4.1'"
    )
    standard_clause_id: str | None = Field(
        default=None, description="知识库中对应的条款 ID（如 '5.2'）"
    )
    suggestion: str = Field(..., description="修改建议")
    evidence: str = Field(
        ...,
        description=(
            "缺陷证据描述（来自矢量数据或 VLM 视觉理解），"
            "如 '标题栏 MATERIAL 字段为空'"
        ),
    )


# ===== SubTask 4.3：三层语义模型 =====


class GeometryLayer(BaseModel):
    """几何层：基本图元的坐标与参数。"""

    lines: list[dict[str, Any]] = Field(
        default_factory=list, description="线段列表，每条含 start/end/length"
    )
    circles: list[dict[str, Any]] = Field(
        default_factory=list, description="圆列表，每条含 center/radius"
    )
    arcs: list[dict[str, Any]] = Field(
        default_factory=list, description="圆弧列表，每条含 center/radius/angles"
    )
    polylines: list[dict[str, Any]] = Field(
        default_factory=list, description="多段线列表，每条含 vertices/is_closed"
    )
    texts: list[dict[str, Any]] = Field(
        default_factory=list, description="文字列表，每条含 position/content/height"
    )
    others: list[dict[str, Any]] = Field(
        default_factory=list, description="其他图元（SPLINE/ELLIPSE/HATCH 等）"
    )


class TopologyLayer(BaseModel):
    """拓扑层：图元间的连接与关系。"""

    shared_endpoints: list[dict[str, Any]] = Field(
        default_factory=list,
        description="共享端点关系，每条含 entity_a/entity_b/point",
    )
    tangencies: list[dict[str, Any]] = Field(
        default_factory=list, description="相切关系"
    )
    concentric_pairs: list[dict[str, Any]] = Field(
        default_factory=list, description="同心圆关系"
    )


class SemanticLayer(BaseModel):
    """语义层：标注/标题栏/技术要求等业务语义。"""

    dimension_count: int = Field(default=0, description="尺寸标注总数")
    dimension_types: dict[str, int] = Field(
        default_factory=dict, description="按类型统计的标注数"
    )
    has_title_block: bool = Field(default=False, description="是否检测到标题栏")
    title_block_fields: dict[str, str | None] = Field(
        default_factory=dict, description="标题栏字段值"
    )
    has_tolerance: bool = Field(default=False, description="是否含形位公差标注")
    has_surface_roughness: bool = Field(
        default=False, description="是否含表面粗糙度符号"
    )
    layer_names: list[str] = Field(
        default_factory=list, description="所有图层名"
    )
    vlm_ocr_extras: dict[str, Any] = Field(
        default_factory=dict,
        description="VLM OCR 补充信息（标题/件号/材料/技术要求等）",
    )


class SemanticModel(BaseModel):
    """融合矢量数据与视觉理解的"几何/拓扑/语义"三层结构化对象。

    由 fuse_to_semantic_model() 产出，作为 LLM 推理与规则引擎的统一输入。
    """

    geometry: GeometryLayer = Field(
        default_factory=GeometryLayer, description="几何层"
    )
    topology: TopologyLayer = Field(
        default_factory=TopologyLayer, description="拓扑层"
    )
    semantic: SemanticLayer = Field(
        default_factory=SemanticLayer, description="语义层"
    )
    source_file: str = Field(default="", description="源文件路径")
    stats: dict[str, Any] = Field(
        default_factory=dict, description="汇总统计信息"
    )


# ===== 审图结果 =====


class ReviewResult(BaseModel):
    """审图任务最终结果。"""

    task_id: str = Field(..., description="Celery 任务 ID")
    file_key: str = Field(..., description="输入文件 key")
    file_type: str = Field(..., description="输入文件类型")
    status: Literal["completed", "failed"] = Field(
        default="completed", description="任务状态"
    )
    compliance_score: float = Field(
        ..., ge=0.0, le=100.0, description="合规性评分（0-100）"
    )
    defects: list[DefectItem] = Field(
        default_factory=list, description="缺陷列表"
    )
    standards_applied: list[str] = Field(
        default_factory=list, description="实际应用的规范集合"
    )
    review_mode: ReviewMode = Field(
        ..., description="实际审图模式（vlm/vector_only/rule_engine）"
    )
    report_path: str | None = Field(
        default=None, description="HTML 报告路径（相对或绝对）"
    )
    pdf_report_path: str | None = Field(
        default=None, description="PDF 报告路径（无则为 None）"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="附加元信息（耗时/模型/版本等）"
    )
    # Task 9.6：精度分级（向后兼容：默认 REFERENCE_LEVEL，原有调用方无感知）
    precision_level: PrecisionLevel = Field(
        default=PrecisionLevel.REFERENCE_LEVEL,
        description="精度等级（依据 spec.md R5：vector_level/reference_level/sketch_level）",
    )
    precision_evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="精度判定证据（PrecisionEvidence 序列化结果）",
    )


# ===== 报告模板数据 =====


class ReviewReportData(BaseModel):
    """HTML/PDF 报告模板数据。

    传递给 Jinja2 模板，包含报告所需的所有信息。
    """

    task_id: str
    file_key: str
    file_type: str
    compliance_score: float
    severity_counts: dict[str, int] = Field(
        default_factory=dict, description="按严重等级统计的缺陷数"
    )
    defects: list[DefectItem] = Field(default_factory=list)
    standards_applied: list[str] = Field(default_factory=list)
    review_mode: ReviewMode
    image_filename: str | None = Field(
        default=None, description="渲染图片文件名（用于报告内嵌）"
    )
    image_base64: str | None = Field(
        default=None, description="渲染图片 base64（直接内嵌 HTML）"
    )
    generated_at: str = Field(default="", description="报告生成时间 ISO 字符串")
    metadata: dict[str, Any] = Field(default_factory=dict)
