"""SolidWorks 零件/装配体结构化表示 schema（SubTask 7.2）。

与 CADIntermediateModel（工程图态）互补：本 schema 表示 SLDPRT/SLDASM 的
参数化模型信息——特征树、尺寸、形位公差、表面粗糙度、技术要求、明细栏、配合。

设计原则：
- 字段尽量可选，避免不同 SolidWorks 版本/文件类型字段缺失导致解析失败
- 单位：长度默认毫米（SolidWorks API 内部为米，reader 转换为毫米）
- 几何坐标统一 3D（与 CADIntermediateModel 一致）
- 不做业务校验（审图规则由 Task 4 实现）

参考：
- SolidWorks API: https://help.solidworks.com/2025/english/api/sldworksapiprogguide/
- spec.md §"SolidWorks 二次开发方案对比" 与"ADDED Requirements"
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ===== 枚举常量（字符串字面量，便于序列化与下游消费）=====

DocType = Literal["part", "assembly", "drawing", "unknown"]

FeatureKind = Literal[
    "extrusion",        # 拉伸
    "revolve",          # 旋转
    "sweep",            # 扫描
    "loft",             # 放样
    "fillet",           # 圆角
    "chamfer",          # 倒角
    "hole",             # 孔
    "shell",            # 抽壳
    "rib",              # 筋
    "draft",            # 拔模
    "pattern",          # 阵列
    "mirror",           # 镜像
    "sketch",           # 草图
    "plane",            # 基准面
    "axis",             # 基准轴
    "mate",             # 配合（装配体）
    "mate_reference",   # 配合参考
    "derived_pattern",  # 派生阵列
    "inserted_part",    # 插入的零件
    "unknown",
]

DimensionType = Literal[
    "linear",           # 线性尺寸
    "angular",          # 角度尺寸
    "radial",           # 半径/直径尺寸
    "ordinate",         # 坐标尺寸
    "unknown",
]

ToleranceType = Literal[
    "none",             # 无公差
    "nominal",          # 基本尺寸（理论正确）
    "symmetric",        # ±对称公差
    "bilateral",        # 不对称双向公差
    "limit",            # 极限尺寸
    "min_max",          # 最小/最大
    "geometric",        # 形位公差（GTol）
    "unknown",
]

# 形位公差类型（GB/T 1182 / ISO 1101）
GeometricToleranceType = Literal[
    "straightness",     # 直线度 ─
    "flatness",         # 平面度 ⏥
    "circularity",      # 圆度 ○
    "cylindricity",     # 圆柱度 ⌭
    "line_profile",     # 线轮廓度 ⌒
    "surface_profile",  # 面轮廓度 ⌓
    "parallelism",      # 平行度 ∥
    "perpendicularity", # 垂直度 ⊥
    "angularity",       # 倾斜度 ∠
    "position",         # 位置度 ⊕
    "concentricity",    # 同轴度 ◎
    "symmetry",         # 对称度 ⌯
    "circular_runout",  # 圆跳动 ↗
    "total_runout",     # 全跳动 ↗↗
    "unknown",
]

SurfaceFinishRoughness = Literal["Ra", "Rz", "Rmax", "Rt", "Rp", "Rq", "unknown"]

MateType = Literal[
    "coincident",       # 重合
    "concentric",       # 同轴
    "parallel",         # 平行
    "perpendicular",    # 垂直
    "tangent",          # 相切
    "width",            # 宽度
    "distance",         # 距离
    "angle",            # 角度
    "lock",             # 锁定
    "cam",              # 凸轮
    "slot",             # 槽
    "hinge",            # 铰链
    "gear",             # 齿轮
    "rack_pinion",      # 齿轮齿条
    "screw",            # 螺旋
    "universal_joint",  # 万向节
    "linear_coupler",   # 线性耦合器
    "path",             # 路径
    "unknown",
]


# ===== 子模型 =====


class SWFeature(BaseModel):
    """特征树节点。

    SolidWorks API 来源：
    - Feature.Name：特征名（如 "Boss-Extrude1"）
    - Feature.GetTypeName2()：类型名（如 "Extrusion"）
    - Feature.GetSpecificFeature2()：具体特征对象
    - Feature.GetFirstChildFeature() / GetNextSubFeature()：子特征遍历
    """

    name: str
    kind: FeatureKind = "unknown"
    type_name: str | None = None  # SolidWorks 原始类型名（如 "Extrusion"/"Revolution"/"Cut-Extrude"）
    is_suppressed: bool = False  # 是否被压缩（压缩特征不参与几何计算）
    is_rollback: bool = False  # 是否处于回滚状态
    parameters: dict[str, Any] = Field(default_factory=dict)  # 特征参数（如拉伸深度/方向）
    children: list[SWFeature] = Field(default_factory=list)  # 子特征（嵌套特征树）


class SWDimension(BaseModel):
    """尺寸标注。

    SolidWorks API 来源：
    - ModelDoc2.Parameter(name)：通过全名获取 Dimension 对象
    - Dimension.SystemValue：SI 单位值（米）
    - Dimension.ToleranceType / ToleranceMinValue / ToleranceMaxValue
    - DisplayDimension.GetText2()：显示文本
    """

    name: str  # 尺寸全名（如 "D1@Sketch1"）
    type: DimensionType = "unknown"
    value: float | None = None  # 名义值（毫米）
    unit: str = "mm"
    tolerance_type: ToleranceType = "none"
    tolerance_plus: float | None = None  # 上偏差（毫米，对称公差为 ±值）
    tolerance_minus: float | None = None  # 下偏差（毫米）
    display_text: str | None = None  # 图纸显示文本（含符号与公差）
    feature_name: str | None = None  # 所属特征名（如 "Sketch1"）
    is_driven: bool = False  # 是否从动尺寸（参考尺寸）


class SWGeometricTolerance(BaseModel):
    """形位公差（GB/T 1182 / ISO 1101）。

    SolidWorks API 来源：
    - 注解遍历：ModelDoc2.Extension.GetAnnotations() 或 GetFirstDisplayDimension
    - GTol 对象：AnnotationType = swAnnotationType_GTol
    - GTol.GetFrameText2()：公差框格文本
    """

    type: GeometricToleranceType = "unknown"
    value: float | None = None  # 公差值（毫米）
    material_condition: Literal["MMC", "LMC", "RFS", "unknown"] = "unknown"  # 最大/最小实体要求
    datum_primary: str | None = None  # 第一基准
    datum_secondary: str | None = None  # 第二基准
    datum_tertiary: str | None = None  # 第三基准
    raw_text: str | None = None  # 原始框格文本（兜底）
    attached_entity: str | None = None  # 附加实体标识（面/边/轴）


class SWSurfaceFinish(BaseModel):
    """表面粗糙度（GB/T 131）。

    SolidWorks API 来源：
    - 注解：swAnnotationType_SurfFinishSymbol
    - Sw3DPropertyHandler / SurfaceFinishSymbol
    """

    roughness: SurfaceFinishRoughness = "Ra"
    value: float | None = None  # 数值（μm）
    machining_method: str | None = None  # 加工方法（如 "车"/"铣"）
    direction: str | None = None  # 纹理方向（如 "=" "⊥" "X" "M" "C" "R" "P"）
    removal_required: bool | None = None  # 是否要求去除材料
    raw_text: str | None = None  # 原始符号文本
    attached_entity: str | None = None  # 附加面标识


class SWTechnicalNote(BaseModel):
    """技术要求（文本注解）。

    SolidWorks SLDPRT/SLDASM 的技术要求通常存储在：
    1. 文件自定义属性（File Summary Information → Custom）
    2. 工程图 Notes（SLDDRW 中的注释文本，SLDPRT/SLDASM 没有 Notes）
    3. Design Binder / 异型孔向导说明等

    reader 兼容从自定义属性提取，键名常见：技术要求 / TechnicalRequirements / Notes
    """

    category: Literal[
        "general",        # 一般要求
        "heat_treat",     # 热处理
        "surface_treat",  # 表面处理
        "machining",      # 机械加工
        "inspection",     # 检验要求
        "assembly",       # 装配要求
        "other",          # 其他
    ] = "general"
    text: str
    source: Literal["custom_property", "note", "design_binder", "unknown"] = "unknown"


class SWBOMItem(BaseModel):
    """明细栏（BOM）单项。

    SolidWorks SLDASM 装配体 BOM 提取来源：
    1. AssemblyDoc.FeatureManager.GetBomFeatures() → BOM 表特征
    2. TableAnnotation 遍历单元格
    3. Component2 自定义属性（件号/材料/重量等）
    """

    item_number: int  # 件号
    part_number: str | None = None  # 图号/代号
    description: str | None = None  # 名称/描述
    quantity: int = 1
    material: str | None = None  # 材料牌号
    mass: float | None = None  # 单件质量（kg）
    total_mass: float | None = None  # 总质量（kg）
    configuration: str | None = None  # 引用配置
    source_file: str | None = None  # 引用文件路径
    custom_properties: dict[str, str] = Field(default_factory=dict)  # 其他自定义属性


class SWComponent(BaseModel):
    """装配体中的组件（引用一个 SLDPRT/SLDASM）。"""

    name: str  # 组件名（如 "法兰盘-1"）
    source_file: str | None = None  # 引用文件路径
    configuration: str | None = None  # 引用配置
    instance_id: int = 1  # 实例号
    is_suppressed: bool = False  # 是否被压缩
    is_flexible: bool = False  # 是否为柔性子装配
    transform: list[float] | None = None  # 4×4 变换矩阵（行主序，16 个 double）
    children: list[SWComponent] = Field(default_factory=list)  # 子组件（嵌套装配）


class SWMate(BaseModel):
    """装配体配合。

    SolidWorks API 来源：
    - AssemblyDoc.GetMates() → Mate2 对象数组
    - Mate2.Type → swMateType_e
    - Mate2.MateEntity(0/1) → 配合实体
    """

    name: str
    type: MateType = "unknown"
    is_suppressed: bool = False
    component_1: str | None = None  # 配合组件 1 名称
    component_2: str | None = None  # 配合组件 2 名称
    entity_1: str | None = None  # 配合实体 1 标识（面/边/顶点）
    entity_2: str | None = None  # 配合实体 2 标识
    distance: float | None = None  # 距离/角度配合的数值（毫米/度）
    alignment: Literal["aligned", "anti_aligned", "none", "unknown"] = "unknown"


class SWCustomProperty(BaseModel):
    """文件自定义属性（Configuration-Specific 或 File-Level）。"""

    name: str
    value: str | None = None
    configuration: str | None = None  # 配置名（None 表示文件级）


class SWMassProperty(BaseModel):
    """质量属性（来自 MassProperties API）。"""

    mass: float | None = None  # kg
    volume: float | None = None  # 立方毫米
    surface_area: float | None = None  # 平方毫米
    center_of_mass: tuple[float, float, float] | None = None  # 重心坐标（毫米）
    principal_axes: list[tuple[float, float, float]] | None = None  # 主惯性轴
    principal_moments: list[float] | None = None  # 主惯性矩


# ===== 顶层模型 =====


class SolidWorksModel(BaseModel):
    """SolidWorks SLDPRT/SLDASM 结构化表示。

    所有字段可选，便于不同文件类型与 SolidWorks 版本的兼容性。
    """

    source_file: str
    doc_type: DocType = "unknown"
    revision: str | None = None  # SolidWorks 版本号（如 "33.3.0"）
    units: str = "mm"  # 文件单位（默认毫米）

    # 通用元数据
    title: str | None = None  # 文件标题（File Summary）
    subject: str | None = None
    author: str | None = None
    company: str | None = None
    created_date: str | None = None
    modified_date: str | None = None

    # 零件/装配通用
    features: list[SWFeature] = Field(default_factory=list)  # 特征树（顶层）
    dimensions: list[SWDimension] = Field(default_factory=list)  # 全局尺寸列表
    geometric_tolerances: list[SWGeometricTolerance] = Field(default_factory=list)
    surface_finishes: list[SWSurfaceFinish] = Field(default_factory=list)
    technical_notes: list[SWTechnicalNote] = Field(default_factory=list)
    custom_properties: list[SWCustomProperty] = Field(default_factory=list)
    mass_properties: SWMassProperty | None = None

    # 装配体专用
    components: list[SWComponent] = Field(default_factory=list)  # 顶层组件
    mates: list[SWMate] = Field(default_factory=list)
    bom_items: list[SWBOMItem] = Field(default_factory=list)

    # 兜底
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)  # 提取过程中的非致命警告
