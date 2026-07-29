"""装配规范 schema（Task 10.1，AssemCAD 范式）。

本 schema 定义"公理化可验证装配规范"的结构化表示，参考
AssemCAD（上海 AI 实验室, 2026）的 axiom-grounded 范式：
- 类型化零件（TypedPart）：参数化的零件定义
- 几何 Port：零件上的可配合接口（面/轴/孔等）
- 可执行 Mate（MateSpec）：两个 Port 之间的约束
- 工程公理（EngineeringAxiom）：装配体级约束规则

与 SolidWorksModel 互补：
- SolidWorksModel 表示"已存在"的 SLDPRT/SLDASM 解析结果
- AssemblySpec 表示"待生成"的装配规范（LLM 输出 → 验证 → 生成）

参考：
- AssemCAD: https://arxiv.org/html/2607.05123v1
- spec.md §"Scenario: 自然语言生成装配体"
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# ===== 枚举 =====

PortType = Literal[
    "planar_face",   # 平面
    "cylindrical",   # 圆柱面（外/内通过 normal_direction 区分）
    "circular_edge", # 圆形边
    "linear_edge",   # 直线边
    "vertex",        # 顶点
    "axis",          # 基准轴
    "origin",        # 原点
    "unknown",
]

MateType = Literal[
    "coincident",     # 重合（面/边/点）
    "concentric",     # 同轴（圆柱面）
    "parallel",       # 平行（平面）
    "perpendicular",  # 垂直（平面）
    "tangent",        # 相切
    "distance",       # 距离
    "angle",          # 角度
    "lock",           # 锁定（全部自由度约束）
    "unknown",
]

AxiomCategory = Literal[
    "interference",      # 干涉检查：零件之间不允许几何相交
    "connectivity",      # 图连通性：装配关系图必须连通
    "degree_of_freedom", # 自由度约束：装配体应被完全约束
    "interface_match",   # 接口匹配：Port 类型与 Mate 类型必须兼容
    "bom_complete",      # BOM 完整性：每个组件必须有对应 BOM 项
    "custom",            # 自定义
]


# ===== 子模型 =====


class Port(BaseModel):
    """零件上的可配合接口。

    Port 是 AssemCAD 范式的核心抽象：每个零件声明一组 Port，
    Mate 通过引用两个 Port 建立约束。Port 的几何信息用于：
    1. 验证 Mate 类型与 Port 类型的兼容性（如 concentric 需两个 cylindrical Port）
    2. 计算确定性 mate 变换矩阵（mate_library.py）
    3. B-Rep 接口验证（如果零件有 STEP 文件，可校验 Port 是否真实存在）

    坐标系：零件局部坐标系，单位 mm。
    """

    name: str  # Port 唯一名（零件内唯一，如 "bottom_face"/"shaft_axis"）
    type: PortType = "unknown"
    # 几何参数（dict，按 PortType 不同字段不同）
    # - planar_face: {"origin": [x,y,z], "normal": [nx,ny,nz]}
    # - cylindrical: {"axis_point": [x,y,z], "axis_dir": [dx,dy,dz], "radius": r}
    # - circular_edge: {"center": [x,y,z], "normal": [nx,ny,nz], "radius": r}
    # - linear_edge: {"start": [x,y,z], "end": [x,y,z]}
    # - vertex: {"point": [x,y,z]}
    # - axis: {"point": [x,y,z], "direction": [dx,dy,dz]}
    # - origin: {}
    geometry: dict[str, Any] = Field(default_factory=dict)

    # 可选：对应 SolidWorks Feature 名（生成时用于 SelectByID2）
    sw_feature_name: str | None = None

    # 可选：B-Rep 验证信息（如果零件有 STEP 文件）
    brep_validated: bool = False
    brep_error: str | None = None


class TypedPart(BaseModel):
    """类型化零件定义（AssemCAD 范式核心）。

    TypedPart 是"参数化零件 + Port 集合"的组合：
    - 参数定义（parameters）：零件的尺寸参数（如螺栓的 M/d/L）
    - Port 集合：零件上可被 Mate 引用的接口
    - 生成方式（generator）：CadQuery 代码 / 标准件工厂名 / STEP 文件引用

    设计原则：
    - 类型化：每个 TypedPart 有 part_type 标识（如 "bolt"/"bearing"/"shaft"）
    - 参数化：parameters 是 dict，允许任意参数（按 part_type 约束由 standard_parts.py）
    - 可验证：Port 可在生成后被 B-Rep 引擎校验
    """

    part_id: str  # 实例唯一 ID（如 "bolt-001"）
    part_type: str  # 类型（如 "bolt"/"bearing"/"shaft"/"plate"/"custom"）
    name: str  # 显示名（如 "M8×30 内六角螺栓"）
    parameters: dict[str, float | str | bool] = Field(default_factory=dict)
    ports: list[Port] = Field(default_factory=list)

    # 生成方式（三选一）
    generator: Literal["cadquery_code", "standard_part", "step_file", "features"] = (
        "standard_part"
    )
    # generator=cadquery_code 时使用
    cadquery_code: str | None = None
    # generator=standard_part 时使用（standard_parts.py 工厂名，如 "bolt_iso4762"）
    standard_part_name: str | None = None
    # generator=step_file 时使用
    step_file: str | None = None
    # generator=features 时使用（SolidWorksModel.features）
    features: list[dict[str, Any]] = Field(default_factory=list)

    # 生成后填充
    generated_file: str | None = None  # 实际生成的 SLDPRT/STEP/DXF 文件路径
    generation_warnings: list[str] = Field(default_factory=list)

    # BOM 信息
    part_number: str | None = None  # 图号/代号
    material: str | None = None  # 材料牌号
    mass: float | None = None  # 单件质量（kg）
    quantity: int = 1  # 数量（同一零件实例数）

    @model_validator(mode="after")
    def _validate_generator_consistency(self) -> "TypedPart":
        """校验 generator 与对应字段一致性。"""
        if self.generator == "cadquery_code" and not self.cadquery_code:
            raise ValueError(
                f"零件 {self.part_id} generator=cadquery_code 但 cadquery_code 为空"
            )
        if self.generator == "standard_part" and not self.standard_part_name:
            raise ValueError(
                f"零件 {self.part_id} generator=standard_part 但 standard_part_name 为空"
            )
        if self.generator == "step_file" and not self.step_file:
            raise ValueError(
                f"零件 {self.part_id} generator=step_file 但 step_file 为空"
            )
        return self


class MateSpec(BaseModel):
    """可执行 Mate（两个 Port 之间的约束）。

    MateSpec 引用两个零件的两个 Port，建立几何约束：
    - coincident：两个平面/边/点重合
    - concentric：两个圆柱面同轴
    - distance：两个平面间固定距离
    - angle：两个平面间固定角度
    - lock：完全锁定（6 自由度全约束）

    确定性 mate 变换矩阵由 mate_library.py 计算：
    给定两个 Port 的 geometry，计算将零件 B 放置到满足 Mate 的变换矩阵。
    """

    name: str  # Mate 唯一名（如 "shaft_to_bearing_concentric"）
    type: MateType = "unknown"
    part_a_id: str  # 零件 A 的 part_id
    port_a_name: str  # 零件 A 的 Port 名
    part_b_id: str  # 零件 B 的 part_id
    port_b_name: str  # 零件 B 的 Port 名

    # 距离/角度 Mate 的数值
    distance_mm: float | None = None  # distance Mate 的距离（mm）
    angle_deg: float | None = None  # angle Mate 的角度（度）

    # 对齐方式
    alignment: Literal["aligned", "anti_aligned", "closest"] = "closest"

    # 生成后填充
    transform_b: list[float] | None = None  # 计算出的零件 B 的 4×4 变换矩阵（行主序）
    is_satisfied: bool = False  # 是否满足约束
    validation_error: str | None = None


class EngineeringAxiom(BaseModel):
    """工程公理（装配体级约束规则）。

    工程公理是 AssemCAD 范式的"可验证规范"：
    装配体不仅要满足 Mate 约束，还要满足工程语义层面的公理。
    validator.py 逐条验证公理，输出 pass/fail/warning 结果。

    示例：
    - interference: "轴与轴承座孔不允许几何干涉"
    - connectivity: "所有零件通过 Mate 形成连通图"
    - degree_of_freedom: "轴在轴向仅有 1 个自由度（旋转）"
    - interface_match: "concentric Mate 必须引用两个 cylindrical Port"
    """

    name: str  # 公理唯一名
    category: AxiomCategory = "custom"
    description: str  # 人类可读描述
    # 公理参数（dict，按 category 不同字段不同）
    # - interference: {"part_a_id": "...", "part_b_id": "...", "tolerance_mm": 0.1}
    # - connectivity: {"allow_orphans": false}
    # - degree_of_freedom: {"part_id": "...", "expected_dof": 1}
    # - interface_match: {"mate_name": "..."}
    parameters: dict[str, Any] = Field(default_factory=dict)

    # 验证结果
    is_satisfied: bool = False
    evidence: str | None = None  # 验证证据（如测量值/失败原因）


# ===== 顶层装配规范 =====


class AssemblySpec(BaseModel):
    """装配规范（AssemCAD 范式核心数据结构）。

    完整的装配规范包含：
    1. 元信息（名称/版本/单位）
    2. 类型化零件列表（TypedPart[]）
    3. Mate 列表（MateSpec[]）
    4. 工程公理列表（EngineeringAxiom[]）

    生成流程（由 celery/tasks/assembly.py 编排）：
    1. LLM 自然语言 → AssemblySpec（assembly_generator.py）
    2. validator.py 验证接口/干涉/连通性/自由度
    3. standard_parts.py 或 sandbox.py 生成各零件 STEP
    4. mate_library.py 计算 mate 变换矩阵
    5. writer.py (SolidWorks) 或 STEP 装配器生成 SLDASM/STEP
    6. bom_exporter.py 输出明细栏
    7. 装配图（DXF）输出
    """

    name: str  # 装配体名（如 "传动组件"）
    version: str = "1.0"
    units: str = "mm"

    parts: list[TypedPart] = Field(default_factory=list)
    mates: list[MateSpec] = Field(default_factory=list)
    axioms: list[EngineeringAxiom] = Field(default_factory=list)

    # 元信息
    description: str | None = None
    author: str | None = None
    created_at: str | None = None  # ISO 8601

    # 生成结果（运行时填充）
    output_files: dict[str, str] = Field(default_factory=dict)
    # {"sldasm": "...", "step": "...", "bom": "...", "drawing_dxf": "..."}
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_references(self) -> "AssemblySpec":
        """校验 Mate 引用的 part_id 与 port_name 都存在。"""
        part_ids = {p.part_id for p in self.parts}
        # part_id 唯一性
        if len(part_ids) != len(self.parts):
            raise ValueError("存在重复的 part_id")
        # port 索引
        port_index: dict[tuple[str, str], Port] = {}
        for p in self.parts:
            for port in p.ports:
                port_index[(p.part_id, port.name)] = port
        # Mate 引用校验
        for mate in self.mates:
            if mate.part_a_id not in part_ids:
                raise ValueError(
                    f"Mate {mate.name} 引用不存在的 part_a_id: {mate.part_a_id}"
                )
            if mate.part_b_id not in part_ids:
                raise ValueError(
                    f"Mate {mate.name} 引用不存在的 part_b_id: {mate.part_b_id}"
                )
            if (mate.part_a_id, mate.port_a_name) not in port_index:
                raise ValueError(
                    f"Mate {mate.name} 引用不存在的 port: "
                    f"{mate.part_a_id}.{mate.port_a_name}"
                )
            if (mate.part_b_id, mate.port_b_name) not in port_index:
                raise ValueError(
                    f"Mate {mate.name} 引用不存在的 port: "
                    f"{mate.part_b_id}.{mate.port_b_name}"
                )
            # distance Mate 必须有 distance_mm
            if mate.type == "distance" and mate.distance_mm is None:
                raise ValueError(
                    f"Mate {mate.name} type=distance 但 distance_mm 为空"
                )
            if mate.type == "angle" and mate.angle_deg is None:
                raise ValueError(
                    f"Mate {mate.name} type=angle 但 angle_deg 为空"
                )
        return self


class AssemblyValidationReport(BaseModel):
    """装配验证报告（Task 10.4 输出）。

    汇总 4 类验证结果：
    1. interface_match：Port-Mate 类型兼容性
    2. interference：零件间几何干涉
    3. connectivity：装配关系图连通性
    4. degree_of_freedom：自由度约束
    """

    assembly_name: str
    is_valid: bool = False  # 总体是否通过（默认 False，验证完成后填充）
    interface_match: list[dict[str, Any]] = Field(default_factory=list)
    interference: list[dict[str, Any]] = Field(default_factory=list)
    connectivity: dict[str, Any] = Field(default_factory=dict)
    degree_of_freedom: list[dict[str, Any]] = Field(default_factory=list)
    axiom_results: list[dict[str, Any]] = Field(default_factory=list)

    # 统计
    passed_count: int = 0
    failed_count: int = 0
    warning_count: int = 0
    elapsed_ms: int = 0


class AssemblyGenerationResult(BaseModel):
    """装配生成结果（Celery 任务返回）。"""

    task_id: str
    assembly_name: str
    success: bool
    validation_report: AssemblyValidationReport | None = None
    output_files: dict[str, str] = Field(default_factory=dict)
    bom_items: list[dict[str, Any]] = Field(default_factory=list)
    elapsed_ms: int = 0
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
