"""SolidWorks SLDPRT/SLDASM 读取器（SubTask 7.2）。

提供从 SolidWorks 文件提取结构化数据的能力：
- 特征树（含子特征递归）
- 尺寸（含公差类型与上下偏差）
- 形位公差（GB/T 1182 / ISO 1101）
- 表面粗糙度（GB/T 131）
- 技术要求（从自定义属性提取）
- 装配体组件树 / 配合 / BOM 明细栏

依赖（与 sw_session.py 同源）：
- pywin32（win32com.client / pythoncom）
- SolidWorks（已启动 Session）

API 参考来源（遵循"以瞎猜接口为耻"原则）：
- SolidWorks API Help 2025: https://help.solidworks.com/2025/english/api/sldworksapiprogguide/
- PartDoc.GetFirstFeature / Feature.GetNextFeature：特征树遍历
- Feature.GetTypeName2：特征类型名
- Feature.GetFirstDisplayDimension / GetNextDisplayDimension：尺寸遍历
- DisplayDimension.GetDimension2 / Dimension.SystemValue：尺寸值（米）
- Dimension.ToleranceType / ToleranceMinValue / ToleranceMaxValue：公差
- ModelDoc2.Extension.GetFirstAnnotation / GetNext：注解遍历
- Annotation.GetType：注解类型（swAnnotationType_e）
- Annotation.GetSpecificAnnotation：具体注解对象
- AssemblyDoc.GetComponents / GetMates：装配体组件/配合
- Component2.GetPathName / ReferencedConfiguration / Transform2
- CustomPropertyManager.GetNames / Get2：自定义属性
- ModelDoc2.Extension.GetMassProperties：质量属性

单位约定：
- 长度：SolidWorks API 内部为米（m），本模块统一转换为毫米（mm）×1000
- 角度：SolidWorks API 返回弧度（rad），本模块统一转换为度（°）×180/π
- 质量：API 返回 kg，保持不变
- 质量属性 GetMassProperties 返回值随文档单位系统（MMGS/IPSI/MKS）变化
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.schemas.solidworks_model import (
    SWBOMItem,
    SWComponent,
    SWCustomProperty,
    SWDimension,
    SWFeature,
    SWGeometricTolerance,
    SWMassProperty,
    SWMate,
    SWSurfaceFinish,
    SWTechnicalNote,
    SolidWorksModel,
)
from app.services.solidworks.sw_session import (
    SW_DOC_ASSEMBLY,
    SW_DOC_PART,
    SolidWorksSession,
)
from app.services.solidworks.worker_pool import solidworks_task

log = get_logger(__name__)


# ===== SolidWorks API 常量（不依赖 swconst.tlb，硬编码避免 COM 类型库加载）=====

# swDocumentTypes_e
_SW_DOC_PART = 1
_SW_DOC_ASSEMBLY = 2
_SW_DOC_DRAWING = 3

# swAnnotationType_e
_SW_ANNO_NOTE = 1
_SW_ANNO_GTOL = 2
_SW_ANNO_DIMENSION = 3
_SW_ANNO_DATUM = 4
_SW_ANNO_SURF_FINISH = 5
_SW_ANNO_BALLOON = 10
_SW_ANNO_BOM_TABLE = 20

# swTolType_e
_SW_TOL_NONE = 0
_SW_TOL_BASIC = 1
_SW_TOL_MIN = 2
_SW_TOL_MAX = 3
_SW_TOL_LIMIT = 4
_SW_TOL_SYMMETRIC = 5
_SW_TOL_BILAT = 6
_SW_TOL_FIT = 7
_SW_TOL_FIT_TOL_ONLY = 8
_SW_TOL_FIT_LIMIT_ONLY = 9
_SW_TOL_MIN_TOL_ONLY = 10
_SW_TOL_MAX_TOL_ONLY = 11

# swMateType_e
_SW_MATE_COINCIDENT = 0
_SW_MATE_CONCENTRIC = 1
_SW_MATE_PERPENDICULAR = 2
_SW_MATE_PARALLEL = 3
_SW_MATE_TANGENT = 4
_SW_MATE_DISTANCE = 5
_SW_MATE_ANGLE = 6
_SW_MATE_UNKNOWN = 7
_SW_MATE_SYMMETRIC = 8
_SW_MATE_CAM = 9
_SW_MATE_GEAR = 10
_SW_MATE_UNIVERSAL_JOINT = 11
_SW_MATE_RACK_PINION = 13
_SW_MATE_LINEAR_COUPLER = 14
_SW_MATE_PATH = 15
_SW_MATE_LOCK = 16
_SW_MATE_LOCK_TOGETHER = 17
_SW_MATE_SCREW = 18
_SW_MATE_HINGE = 20
_SW_MATE_SLOT = 21
_SW_MATE_WIDTH = 22

# swLengthUnit_e
_SW_LENGTH_UNIT_MM = 0
_SW_LENGTH_UNIT_CM = 1
_SW_LENGTH_UNIT_M = 2
_SW_LENGTH_UNIT_INCH = 3

# swUserPreferenceType_e
_SW_DOC_LENGTH_UNIT = 10

# 常见特征类型名 → FeatureKind 映射
# 实测补充：bolt.sldprt 中 Boss-Extrude2 的 type_name 为 "ICE"（Internal Cut Extrusion）
_FEATURE_TYPE_MAP: dict[str, str] = {
    "Extrusion": "extrusion",
    "ExtrudedBoss": "extrusion",
    "ExtrudedCut": "extrusion",
    "Boss-Extrude": "extrusion",
    "Cut-Extrude": "extrusion",
    "ICE": "extrusion",  # Internal Cut Extrusion（实测 bolt.sldprt Boss-Extrude2）
    "Revolution": "revolve",
    "RevolveBoss": "revolve",
    "RevolveCut": "revolve",
    "Boss-Revolve": "revolve",
    "Cut-Revolve": "revolve",
    "Sweep": "sweep",
    "Boss-Sweep": "sweep",
    "Cut-Sweep": "sweep",
    "Loft": "loft",
    "Boss-Loft": "loft",
    "Cut-Loft": "loft",
    "Fillet": "fillet",
    "Chamfer": "chamfer",
    "Hole": "hole",
    "HoleWzd": "hole",
    "SimpleHole": "hole",
    "Shell": "shell",
    "Rib": "rib",
    "Draft": "draft",
    "LinearPattern": "pattern",
    "CircularPattern": "pattern",
    "CurvePattern": "pattern",
    "Mirror": "mirror",
    "MirrorPattern": "mirror",
    "DerivedLPattern": "derived_pattern",
    "DerivedCPattern": "derived_pattern",
    "ProfileFeature": "sketch",
    "Sketch": "sketch",
    "RefPlane": "plane",
    "DatumPlane": "plane",
    "RefAxis": "axis",
    "DatumAxis": "axis",
    "Mate": "mate",
    "MateReference": "mate_reference",
    "InsertedPart": "inserted_part",
    "DerivedPart": "inserted_part",
}


# ===== 公共入口（被 @solidworks_task 装饰）=====


@solidworks_task(timeout=120.0)
def read_sldprt(session: SolidWorksSession, file_path: Path) -> SolidWorksModel:
    """读取 SolidWorks 零件文件（SLDPRT）并提取结构化信息。

    Args:
        session: SolidWorksSession（由 @solidworks_task 注入）
        file_path: SLDPRT 文件路径

    Returns:
        SolidWorksModel（doc_type="part"）

    Raises:
        SolidWorksTaskError: 文件打开失败或读取异常
    """
    path = Path(file_path)
    log.info("sw.reader.read_sldprt.start", file=str(path))
    doc = session.open_document(path, SW_DOC_PART, read_only=True)
    try:
        model = _extract_common(doc, path, doc_type="part", session=session)
        try:
            model.mass_properties = _extract_mass_properties(doc, session=session)
        except Exception as e:  # noqa: BLE001
            model.warnings.append(f"质量属性提取失败: {e}")
        log.info(
            "sw.reader.read_sldprt.done",
            file=str(path),
            features=len(model.features),
            dimensions=len(model.dimensions),
            gtol=len(model.geometric_tolerances),
            sf=len(model.surface_finishes),
        )
        return model
    finally:
        session.close_document(doc, save_changes=False)


@solidworks_task(timeout=180.0)
def read_sldasm(session: SolidWorksSession, file_path: Path) -> SolidWorksModel:
    """读取 SolidWorks 装配体文件（SLDASM）并提取结构化信息。

    Args:
        session: SolidWorksSession（由 @solidworks_task 注入）
        file_path: SLDASM 文件路径

    Returns:
        SolidWorksModel（doc_type="assembly"，含 components/mates/bom_items）
    """
    path = Path(file_path)
    log.info("sw.reader.read_sldasm.start", file=str(path))
    doc = session.open_document(path, SW_DOC_ASSEMBLY, read_only=True)
    try:
        model = _extract_common(doc, path, doc_type="assembly", session=session)
        try:
            model.components = _extract_components(doc, session=session)
        except Exception as e:  # noqa: BLE001
            model.warnings.append(f"组件树提取失败: {e}")
        try:
            model.mates = _extract_mates(doc, session=session)
        except Exception as e:  # noqa: BLE001
            model.warnings.append(f"配合提取失败: {e}")
        try:
            model.bom_items = _extract_bom(doc, session=session)
        except Exception as e:  # noqa: BLE001
            model.warnings.append(f"BOM 提取失败: {e}")
        try:
            model.mass_properties = _extract_mass_properties(doc, session=session)
        except Exception as e:  # noqa: BLE001
            model.warnings.append(f"质量属性提取失败: {e}")
        log.info(
            "sw.reader.read_sldasm.done",
            file=str(path),
            components=len(model.components),
            mates=len(model.mates),
            bom=len(model.bom_items),
        )
        return model
    finally:
        session.close_document(doc, save_changes=False)


# ===== 通用提取（零件/装配体共用）=====


def _extract_common(
    doc: Any,
    path: Path,
    doc_type: str,
    session: SolidWorksSession,
) -> SolidWorksModel:
    """提取零件/装配体通用字段。"""
    model = SolidWorksModel(
        source_file=str(path),
        doc_type=doc_type,  # type: ignore[arg-type]
        revision=session.revision,
    )
    try:
        model.units = _detect_length_unit(doc)
    except Exception as e:  # noqa: BLE001
        model.warnings.append(f"单位检测失败: {e}")
    try:
        model.features = _traverse_feature_tree(doc, session=session)
    except Exception as e:  # noqa: BLE001
        model.warnings.append(f"特征树遍历失败: {e}")
    try:
        model.dimensions = _extract_dimensions(doc, session=session)
    except Exception as e:  # noqa: BLE001
        model.warnings.append(f"尺寸提取失败: {e}")
    try:
        model.geometric_tolerances, model.surface_finishes, model.technical_notes = (
            _extract_annotations(doc, session=session)
        )
    except Exception as e:  # noqa: BLE001
        model.warnings.append(f"注解提取失败: {e}")
    try:
        model.custom_properties = _extract_custom_properties(doc, session=session)
    except Exception as e:  # noqa: BLE001
        model.warnings.append(f"自定义属性提取失败: {e}")
    try:
        model.technical_notes.extend(_extract_technical_notes_from_props(doc, session=session))
    except Exception as e:  # noqa: BLE001
        model.warnings.append(f"技术要求(自定义属性)提取失败: {e}")
    return model


def _detect_length_unit(doc: Any) -> str:
    """检测文档长度单位。"""
    try:
        unit_enum = doc.GetUserPreferenceIntegerValue(_SW_DOC_LENGTH_UNIT)
        unit_map = {
            _SW_LENGTH_UNIT_MM: "mm",
            _SW_LENGTH_UNIT_CM: "cm",
            _SW_LENGTH_UNIT_M: "m",
            _SW_LENGTH_UNIT_INCH: "inch",
        }
        return unit_map.get(int(unit_enum), "mm")
    except Exception:  # noqa: BLE001
        return "mm"


# ===== 特征树遍历 =====


# SolidWorks 特征管理器中的虚拟文件夹类型名（不对应实际特征）
# 实测确认：bolt.sldprt 遍历会返回 "Favorites"、"History"、"Selection Sets" 等
# 文件夹节点，这些节点 GetTypeName2() 返回下列值之一，应跳过避免污染特征列表。
# 来源：SolidWorks API Help - swFeatureNameID_e + 实测 bolt.sldprt/can.sldasm
_VIRTUAL_FOLDER_TYPES: set[str] = {
    "FtrFolder",            # 特征文件夹（Favorites/History 等）
    "HistoryFolder",        # 历史文件夹
    "FavoriteFolder",       # 收藏夹文件夹（注意：单数 FavoriteFolder）
    "SelectionSetFolder",   # 选择集文件夹
    "SensorFolder",         # 传感器文件夹
    "DocsFolder",           # 设计活页夹文件夹
    "DetailCabinet",        # 注解文件夹（Annotations）
    "InkMarkupFolder",      # 标记文件夹（Markups）
    "EnvFolder",            # 光源与相机文件夹
    "SolidBodyFolder",      # 实体文件夹
    "SurfaceBodyFolder",    # 曲面实体文件夹
    "CommentsFolder",       # 注释文件夹
    "EqnFolder",            # 方程式文件夹
    "ConfigTableFolder",    # 配置表文件夹
    "ToolboxFolder",        # Toolbox 文件夹
    "DesignBinder",         # 设计绑定文件夹
    "AnnotationsFolder",    # 注解文件夹（旧名）
    "LightsFolder",         # 光源文件夹（旧名）
    "SceneFolder",          # 场景文件夹
    "MaterialFolder",       # 材质文件夹
    "AppearanceFolder",     # 外观文件夹
    "DecalsFolder",         # 贴图文件夹
    "SurfaceFinishFolder",  # 表面粗糙度文件夹
}


def _get_typelib_module(session: SolidWorksSession) -> Any:
    """从 SolidWorksSession 获取类型库模块（强类型接口类集合）。

    Returns:
        类型库模块（None 表示动态 Dispatch 模式）
    """
    return getattr(session, "typelib_module", None)


def _wrap_as_ifeature(feat: Any, sw_module: Any) -> Any:
    """将 COM Feature 对象包装为 IFeature 强类型接口。

    Args:
        feat: 动态 Dispatch (CDispatch) 或已包装的 IFeature
        sw_module: 类型库模块（None 时直接返回 feat）

    Returns:
        IFeature 实例（或原对象如果 sw_module 为 None）
    """
    if sw_module is None or feat is None:
        return feat
    # 已是强类型则直接返回
    if isinstance(feat, sw_module.IFeature):
        return feat
    # 动态 Dispatch 需包装
    if hasattr(feat, "_oleobj_"):
        try:
            return sw_module.IFeature(feat._oleobj_)
        except Exception as e:  # noqa: BLE001
            log.debug("sw.reader.wrap_ifeature_failed", error=str(e))
    return feat


def _wrap_as_imodeldoc2(doc: Any, sw_module: Any) -> Any:
    """将 COM ModelDoc2 对象包装为 IModelDoc2 强类型接口。

    Args:
        doc: 动态 Dispatch 或已包装的 IModelDoc2
        sw_module: 类型库模块（None 时直接返回 doc）

    Returns:
        IModelDoc2 实例（或原对象如果 sw_module 为 None）
    """
    if sw_module is None or doc is None:
        return doc
    if isinstance(doc, sw_module.IModelDoc2):
        return doc
    if hasattr(doc, "_oleobj_"):
        try:
            return sw_module.IModelDoc2(doc._oleobj_)
        except Exception as e:  # noqa: BLE001
            log.debug("sw.reader.wrap_imodeldoc2_failed", error=str(e))
    return doc


def _traverse_feature_tree(
    doc: Any, session: SolidWorksSession | None = None
) -> list[SWFeature]:
    """递归遍历特征树，返回顶层特征列表（含子特征嵌套）。

    API（强类型路径，已实测验证）：
    - IModelDoc2.FirstFeature（注意：不是 GetFirstFeature）
    - IFeature.GetNextFeature（同级遍历）
    - IFeature.GetFirstSubFeature（子级遍历，注意：不是 GetFirstChildFeature）
    - IFeature.GetNextSubFeature（子级同级遍历）

    动态 Dispatch 回退路径（不推荐，部分 API 可能失败）：
    - doc.GetFirstFeature()
    - feat.GetNextFeature()

    过滤规则：跳过虚拟文件夹节点（Favorites/History 等），
    这些节点在特征树中存在但不对应实际特征。
    """
    features: list[SWFeature] = []
    sw_module = _get_typelib_module(session) if session else None

    # 强类型路径：包装 doc 为 IModelDoc2
    if sw_module is not None:
        doc = _wrap_as_imodeldoc2(doc, sw_module)

    # 获取第一个特征
    # 强类型 IModelDoc2.FirstFeature 是属性（无参数）
    # 动态 Dispatch GetFirstFeature 是方法（需调用）
    feat: Any = None
    try:
        if sw_module is not None:
            # 强类型 IModelDoc2.FirstFeature() 返回 Dispatch（需进一步包装）
            feat = doc.FirstFeature()
        else:
            # 动态 Dispatch 回退
            feat = doc.GetFirstFeature()
    except Exception as e:  # noqa: BLE001
        log.warning("sw.reader.get_first_feature_failed", error=str(e))
        return features

    while feat is not None:
        # 包装为 IFeature 强类型
        feat = _wrap_as_ifeature(feat, sw_module)
        sw_feat = _convert_feature(feat, sw_module)
        if sw_feat is not None:
            features.append(sw_feat)
        try:
            feat = feat.GetNextFeature()
        except Exception as e:  # noqa: BLE001
            log.warning("sw.reader.get_next_feature_failed", error=str(e))
            break
    return features


def _convert_feature(feat: Any, sw_module: Any = None) -> SWFeature | None:
    """将 SolidWorks Feature 对象转为 SWFeature（递归子特征）。

    Args:
        feat: 已包装为 IFeature 的强类型对象，或动态 Dispatch
        sw_module: 类型库模块（None 时使用动态 Dispatch 调用）

    过滤规则：跳过虚拟文件夹节点（Favorites/History 等），
    这些节点在特征树中存在但不对应实际特征。
    """
    # 包装为 IFeature 强类型（若尚未包装）
    feat = _wrap_as_ifeature(feat, sw_module)
    try:
        name = str(feat.Name)
    except Exception:  # noqa: BLE001
        return None
    type_name: str | None = None
    try:
        type_name = str(feat.GetTypeName2())
    except Exception:  # noqa: BLE001
        type_name = None

    # 虚拟文件夹过滤（Favorites/History/Annotations 等非实际特征）
    if type_name in _VIRTUAL_FOLDER_TYPES:
        log.debug("sw.reader.skip_virtual_folder", name=name, type=type_name)
        return None

    is_suppressed = False
    try:
        is_suppressed = bool(feat.IsSuppressed())
    except Exception:  # noqa: BLE001
        try:
            is_suppressed = bool(feat.GetSuppressionCondition())
        except Exception:  # noqa: BLE001
            pass
    is_rollback = False
    try:
        is_rollback = bool(feat.IsRolledBack())
    except Exception:  # noqa: BLE001
        pass
    kind = _FEATURE_TYPE_MAP.get(type_name or "", "unknown")
    parameters = _extract_feature_parameters(feat, type_name, kind)
    children: list[SWFeature] = []
    try:
        # API 实测：GetFirstSubFeature / GetNextSubFeature（不是 GetFirstChildFeature）
        sub_feat = feat.GetFirstSubFeature()
        while sub_feat is not None:
            sub_sw_feat = _convert_feature(sub_feat, sw_module)
            if sub_sw_feat is not None:
                children.append(sub_sw_feat)
            try:
                sub_feat = sub_feat.GetNextSubFeature()
            except Exception:  # noqa: BLE001
                break
    except Exception as e:  # noqa: BLE001
        log.debug("sw.reader.subfeature_traverse_failed", feature=name, error=str(e))
    return SWFeature(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        type_name=type_name,
        is_suppressed=is_suppressed,
        is_rollback=is_rollback,
        parameters=parameters,
        children=children,
    )


def _extract_feature_parameters(
    feat: Any, type_name: str | None, kind: str
) -> dict[str, Any]:
    """提取特定类型特征的参数（仅关键参数，不同版本接口差异较大）。

    遵循"实事求是"原则：只提取经 API 文档确认的字段，未确认字段不入库。
    """
    params: dict[str, Any] = {}
    if type_name is None:
        return params
    try:
        specific = feat.GetSpecificFeature2()
        if specific is None:
            return params
        # 拉伸/旋转/圆角/倒角/孔/抽壳 通用模式：GetDefinition + AccessSelections
        if kind in ("extrusion", "revolve", "fillet", "chamfer", "hole", "shell"):
            try:
                feat_def = feat.GetDefinition()
                if feat_def is not None and feat_def.AccessSelections(feat, None):
                    try:
                        if kind == "extrusion":
                            end_cond = getattr(feat_def, "EndCondition", None)
                            if end_cond is not None:
                                params["end_condition"] = int(end_cond)
                            depth = getattr(feat_def, "Depth", None)
                            if depth is not None:
                                params["depth_mm"] = float(depth) * 1000.0
                            flip_dir = getattr(feat_def, "FlipEndDir", None)
                            if flip_dir is not None:
                                params["flip_direction"] = bool(flip_dir)
                        elif kind == "revolve":
                            angle = getattr(feat_def, "Angle", None)
                            if angle is not None:
                                params["angle_deg"] = math.degrees(float(angle))
                            direction = getattr(feat_def, "Direction", None)
                            if direction is not None:
                                params["direction"] = int(direction)
                        elif kind == "fillet":
                            radius = getattr(feat_def, "Radius", None) or getattr(
                                feat_def, "DefaultRadius", None
                            )
                            if radius is not None:
                                params["radius_mm"] = float(radius) * 1000.0
                            fillet_type = getattr(feat_def, "FilletType", None)
                            if fillet_type is not None:
                                params["fillet_type"] = int(fillet_type)
                        elif kind == "chamfer":
                            distance = getattr(feat_def, "Distance", None) or getattr(
                                feat_def, "Distance1", None
                            )
                            if distance is not None:
                                params["distance_mm"] = float(distance) * 1000.0
                            angle = getattr(feat_def, "Angle", None)
                            if angle is not None:
                                params["angle_deg"] = math.degrees(float(angle))
                        elif kind == "hole":
                            diameter = getattr(
                                feat_def, "Diameter", None
                            ) or getattr(feat_def, "DefaultDrillDiameter", None)
                            if diameter is not None:
                                params["diameter_mm"] = float(diameter) * 1000.0
                            depth = getattr(feat_def, "Depth", None) or getattr(
                                feat_def, "HoleDepth", None
                            )
                            if depth is not None:
                                params["depth_mm"] = float(depth) * 1000.0
                        elif kind == "shell":
                            thickness = getattr(
                                feat_def, "Thickness", None
                            ) or getattr(feat_def, "DefaultThickness", None)
                            if thickness is not None:
                                params["thickness_mm"] = float(thickness) * 1000.0
                    finally:
                        feat_def.ReleaseSelectionAccess()
            except Exception as e:  # noqa: BLE001
                log.debug("sw.reader.params_extract_failed", feature=kind, error=str(e))
    except Exception as e:  # noqa: BLE001
        log.debug("sw.reader.feature_specific_failed", feature=kind, error=str(e))
    return params


# ===== 尺寸提取 =====


def _extract_dimensions(
    doc: Any, session: SolidWorksSession | None = None
) -> list[SWDimension]:
    """遍历特征中的 DisplayDimension，提取全部尺寸（去重）。

    API（强类型路径）：
    - IModelDoc2.FirstFeature（属性，非方法）
    - IFeature.GetFirstDisplayDimension / GetNextDisplayDimension
    - DisplayDimension.GetDimension2(index)
    - Dimension.FullName / SystemValue / ToleranceType / ToleranceMinValue / ToleranceMaxValue
    - DisplayDimension.GetText2()

    动态 Dispatch 回退路径：
    - doc.GetFirstFeature()（方法）

    SystemValue 单位为米（SolidWorks 内部 SI），转毫米 ×1000
    """
    dimensions: list[SWDimension] = []
    seen: set[str] = set()
    sw_module = _get_typelib_module(session) if session else None

    # 强类型路径：包装 doc 为 IModelDoc2
    if sw_module is not None:
        doc = _wrap_as_imodeldoc2(doc, sw_module)

    feat = None
    try:
        if sw_module is not None:
            # 强类型 IModelDoc2.FirstFeature（属性，需括号调用）
            feat = doc.FirstFeature()
        else:
            feat = doc.GetFirstFeature()
    except Exception as e:  # noqa: BLE001
        log.warning("sw.reader.dim_get_first_feature_failed", error=str(e))
        return dimensions
    while feat is not None:
        # 包装为 IFeature
        feat = _wrap_as_ifeature(feat, sw_module)
        # 跳过虚拟文件夹节点（无 DisplayDimension）
        try:
            type_name = str(feat.GetTypeName2())
            if type_name in _VIRTUAL_FOLDER_TYPES:
                try:
                    feat = feat.GetNextFeature()
                except Exception:  # noqa: BLE001
                    break
                continue
        except Exception:  # noqa: BLE001
            pass
        try:
            disp_dim = feat.GetFirstDisplayDimension()
        except Exception:  # noqa: BLE001
            disp_dim = None
        while disp_dim is not None:
            sw_dim = _convert_display_dimension(disp_dim, feat)
            if sw_dim is not None and sw_dim.name not in seen:
                dimensions.append(sw_dim)
                seen.add(sw_dim.name)
            try:
                disp_dim = feat.GetNextDisplayDimension(disp_dim)
            except Exception:  # noqa: BLE001
                break
        try:
            feat = feat.GetNextFeature()
        except Exception as e:  # noqa: BLE001
            log.warning("sw.reader.dim_get_next_feature_failed", error=str(e))
            break
    return dimensions


def _convert_display_dimension(disp_dim: Any, feat: Any) -> SWDimension | None:
    """将 DisplayDimension 转为 SWDimension。"""
    try:
        dim = disp_dim.GetDimension2(0)
        if dim is None:
            return None
        name = str(dim.FullName)  # 如 "D1@Sketch1"
        value_m: float | None = None
        try:
            value_m = float(dim.SystemValue)
        except Exception:  # noqa: BLE001
            value_m = None
        value_mm = value_m * 1000.0 if value_m is not None else None
        tol_type_enum = _SW_TOL_NONE
        try:
            tol_type_enum = int(dim.ToleranceType)
        except Exception:  # noqa: BLE001
            tol_type_enum = _SW_TOL_NONE
        tol_type_str = _map_tolerance_type(tol_type_enum)
        tol_plus_mm: float | None = None
        tol_minus_mm: float | None = None
        try:
            if tol_type_enum == _SW_TOL_SYMMETRIC:
                v = float(dim.ToleranceMaxValue)
                tol_plus_mm = v * 1000.0
                tol_minus_mm = -v * 1000.0
            elif tol_type_enum == _SW_TOL_BILAT:
                tol_plus_mm = float(dim.ToleranceMaxValue) * 1000.0
                tol_minus_mm = float(dim.ToleranceMinValue) * 1000.0
            elif tol_type_enum in (_SW_TOL_MAX, _SW_TOL_MAX_TOL_ONLY):
                tol_plus_mm = 0.0
                tol_minus_mm = float(dim.ToleranceMinValue) * 1000.0
            elif tol_type_enum in (_SW_TOL_MIN, _SW_TOL_MIN_TOL_ONLY):
                tol_plus_mm = float(dim.ToleranceMaxValue) * 1000.0
                tol_minus_mm = 0.0
            elif tol_type_enum == _SW_TOL_LIMIT:
                tol_plus_mm = float(dim.ToleranceMaxValue) * 1000.0
                tol_minus_mm = float(dim.ToleranceMinValue) * 1000.0
        except Exception:  # noqa: BLE001
            pass
        display_text: str | None = None
        try:
            display_text = str(disp_dim.GetText2())
        except Exception:  # noqa: BLE001
            display_text = None
        is_driven = False
        try:
            # DisplayDimension.Type2: 0=driving, 1=driven (reference)
            dim_type = int(disp_dim.Type2)
            is_driven = dim_type == 1
        except Exception:  # noqa: BLE001
            pass
        feature_name: str | None = None
        try:
            feature_name = str(feat.Name)
        except Exception:  # noqa: BLE001
            feature_name = None
        dim_type_str = _infer_dimension_type(name, value_mm, display_text)
        return SWDimension(
            name=name,
            type=dim_type_str,  # type: ignore[arg-type]
            value=value_mm,
            unit="mm",
            tolerance_type=tol_type_str,  # type: ignore[arg-type]
            tolerance_plus=tol_plus_mm,
            tolerance_minus=tol_minus_mm,
            display_text=display_text,
            feature_name=feature_name,
            is_driven=is_driven,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("sw.reader.convert_dim_failed", error=str(e))
        return None


def _map_tolerance_type(tol_enum: int) -> str:
    """swTolType_e 枚举值映射为字符串字面量。"""
    mapping = {
        _SW_TOL_NONE: "none",
        _SW_TOL_BASIC: "nominal",
        _SW_TOL_MIN: "min_max",
        _SW_TOL_MAX: "min_max",
        _SW_TOL_LIMIT: "limit",
        _SW_TOL_SYMMETRIC: "symmetric",
        _SW_TOL_BILAT: "bilateral",
        _SW_TOL_FIT: "unknown",  # 配合公差，schema 未细分
        _SW_TOL_FIT_TOL_ONLY: "unknown",
        _SW_TOL_FIT_LIMIT_ONLY: "limit",
        _SW_TOL_MIN_TOL_ONLY: "min_max",
        _SW_TOL_MAX_TOL_ONLY: "min_max",
    }
    return mapping.get(tol_enum, "unknown")


def _infer_dimension_type(
    name: str, value: float | None, display_text: str | None
) -> str:
    """根据尺寸名/显示文本推断尺寸类型（线性/角度/半径等）。

    经验规则：
    - 名前缀 "A" 通常为角度
    - 名前缀 "R" 通常为半径
    - 名前缀 "D" 既可能线性也可能直径，结合显示文本判定
    """
    upper = name.upper()
    if upper.startswith("A"):
        return "angular"
    if upper.startswith("R"):
        return "radial"
    if upper.startswith("D"):
        if display_text and ("Ø" in display_text or "dia" in display_text.lower()):
            return "radial"
        return "linear"
    if display_text:
        if "Ø" in display_text or "⌀" in display_text:
            return "radial"
        if "°" in display_text:
            return "angular"
    return "unknown"


# ===== 注解提取（形位公差 / 表面粗糙度 / 技术要求注释）=====


def _extract_annotations(
    doc: Any, session: SolidWorksSession | None = None
) -> tuple[list[SWGeometricTolerance], list[SWSurfaceFinish], list[SWTechnicalNote]]:
    """遍历文档所有注解，按类型分流到 GTol/SurfaceFinish/Note。

    API（已通过 SolidWorks API Help 2025 核对）：
    - ModelDocExtension.GetAnnotations()：返回所有 Annotation 对象数组
    - Annotation.GetType：swAnnotationType_e
    - Annotation.GetSpecificAnnotation：获取具体注解对象
      - swAnnotationType_GTol → Gtol
      - swAnnotationType_SurfFinish → SurfaceFinishSymbol
      - swAnnotationType_Note → Note
    """
    gtols: list[SWGeometricTolerance] = []
    surface_finishes: list[SWSurfaceFinish] = []
    notes: list[SWTechnicalNote] = []

    # 强类型路径：包装 doc 为 IModelDoc2（Extension 是其属性）
    sw_module = _get_typelib_module(session) if session else None
    if sw_module is not None:
        doc = _wrap_as_imodeldoc2(doc, sw_module)

    try:
        ext = doc.Extension
    except Exception as e:  # noqa: BLE001
        log.warning("sw.reader.get_extension_failed", error=str(e))
        return gtols, surface_finishes, notes

    annotations: Any = None
    try:
        annotations = ext.GetAnnotations()
    except Exception as e:  # noqa: BLE001
        log.warning("sw.reader.get_annotations_failed", error=str(e))
        return gtols, surface_finishes, notes

    if annotations is None:
        return gtols, surface_finishes, notes

    try:
        anno_iter = list(annotations)
    except TypeError:
        anno_iter = [annotations]

    for anno in anno_iter:
        if anno is None:
            continue
        try:
            anno_type = int(anno.GetType())
        except Exception:  # noqa: BLE001
            continue
        try:
            specific = anno.GetSpecificAnnotation()
        except Exception:  # noqa: BLE001
            specific = None
        try:
            if anno_type == _SW_ANNO_GTOL and specific is not None:
                gtol = _convert_gtol(specific, anno)
                if gtol is not None:
                    gtols.append(gtol)
            elif anno_type == _SW_ANNO_SURF_FINISH and specific is not None:
                sf = _convert_surf_finish(specific, anno)
                if sf is not None:
                    surface_finishes.append(sf)
            elif anno_type == _SW_ANNO_NOTE and specific is not None:
                note = _convert_note(specific)
                if note is not None:
                    notes.append(note)
        except Exception as e:  # noqa: BLE001
            log.debug("sw.reader.anno_convert_failed", type=anno_type, error=str(e))

    return gtols, surface_finishes, notes


# 形位公差类型符号 → schema 枚举（GB/T 1182 / ISO 1101）
_GTOL_SYMBOL_MAP: dict[str, str] = {
    "─": "straightness",
    "直线度": "straightness",
    "⏥": "flatness",
    "平面度": "flatness",
    "○": "circularity",
    "圆度": "circularity",
    "⌭": "cylindricity",
    "圆柱度": "cylindricity",
    "⌒": "line_profile",
    "线轮廓度": "line_profile",
    "⌓": "surface_profile",
    "面轮廓度": "surface_profile",
    "∥": "parallelism",
    "平行度": "parallelism",
    "⊥": "perpendicularity",
    "垂直度": "perpendicularity",
    "∠": "angularity",
    "倾斜度": "angularity",
    "⊕": "position",
    "位置度": "position",
    "◎": "concentricity",
    "同轴度": "concentricity",
    "⌯": "symmetry",
    "对称度": "symmetry",
    "↗": "circular_runout",
    "圆跳动": "circular_runout",
    "↗↗": "total_runout",
    "全跳动": "total_runout",
}

# 实体条件修饰符（Maximum/Least Material Condition, Regardless of Feature Size）
_MATERIAL_COND_MAP: dict[str, str] = {
    "M": "MMC",
    "L": "LMC",
    "S": "RFS",
    "P": "RFS",  # Projected tolerance zone
    "F": "RFS",  # Free state
}


def _convert_gtol(specific: Any, anno: Any) -> SWGeometricTolerance | None:
    """将 SolidWorks Gtol 对象转为 SWGeometricTolerance。

    API：
    - Gtol.GetFrameText2()：返回公差框格文本（多框以 \\n 分隔）
      框格结构：[符号][公差值][实体条件] [基准1][基准2][基准3]
    - 不同 SolidWorks 版本接口差异较大，优先 GetFrameText2，失败回退 GetFrameText
    """
    raw_text: str | None = None
    for method in ("GetFrameText2", "GetFrameText"):
        try:
            txt = getattr(specific, method)
            if callable(txt):
                txt = txt()
            if txt:
                raw_text = str(txt)
                break
        except Exception:  # noqa: BLE001
            continue
    if not raw_text:
        return None

    # 多框以换行分隔，仅取第一个完整框解析
    first_frame = raw_text.split("\n")[0].strip()
    gtol_type = _parse_gtol_type(first_frame)
    value_mm, material_cond = _parse_gtol_value_and_material(first_frame)
    datums = _parse_gtol_datums(first_frame)

    attached = None
    try:
        attached = _get_attached_entity_label(anno)
    except Exception:  # noqa: BLE001
        pass

    return SWGeometricTolerance(
        type=gtol_type,  # type: ignore[arg-type]
        value=value_mm,
        material_condition=material_cond,  # type: ignore[arg-type]
        datum_primary=datums[0],
        datum_secondary=datums[1],
        datum_tertiary=datums[2],
        raw_text=raw_text,
        attached_entity=attached,
    )


def _parse_gtol_type(frame: str) -> str:
    """从框格文本首部识别形位公差类型。"""
    for symbol, type_str in _GTOL_SYMBOL_MAP.items():
        if frame.startswith(symbol):
            return type_str
    return "unknown"


def _parse_gtol_value_and_material(
    frame: str,
) -> tuple[float | None, str]:
    """解析公差值与实体条件修饰符。

    框格式样（GB/T 1182）：⌖|Ø0.05|M|A|B|C / ─|0.02 / ⊥|0.1|A
    数值单位：SolidWorks GTol 文本默认与文档单位一致，本模块统一假设为 mm。
    """
    rest = frame
    for symbol in _GTOL_SYMBOL_MAP:
        if rest.startswith(symbol):
            rest = rest[len(symbol):]
            break
    rest = rest.strip()
    # 去除直径符号
    if rest.startswith("Ø") or rest.startswith("⌀") or rest.startswith("D"):
        rest = rest[1:].strip()
    # 提取首个数值（支持小数与科学计数法）
    m = re.search(r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)", rest)
    value: float | None = None
    if m:
        try:
            value = float(m.group(1))
        except ValueError:
            value = None
        rest = rest[m.end():].strip()
    # 实体条件修饰符：紧邻数值后的单字符
    material_cond = "unknown"
    if rest:
        first_char = rest[0].upper()
        if first_char in _MATERIAL_COND_MAP:
            material_cond = _MATERIAL_COND_MAP[first_char]
    return value, material_cond


def _parse_gtol_datums(frame: str) -> list[str | None]:
    """解析基准引用（最多三基准）。"""
    rest = frame
    for symbol in _GTOL_SYMBOL_MAP:
        if rest.startswith(symbol):
            rest = rest[len(symbol):]
            break
    # 去除数值与修饰符前缀
    rest = re.sub(r"^[Ø⌀D]?\s*[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\s*[MLSP]?",
                  "", rest, count=1).strip()
    if not rest:
        return [None, None, None]
    parts = re.split(r"[|,/\s]+", rest)
    datums: list[str | None] = []
    for p in parts[:3]:
        p = p.strip()
        if p:
            datums.append(p)
    while len(datums) < 3:
        datums.append(None)
    return datums


def _convert_surf_finish(
    specific: Any, anno: Any
) -> SWSurfaceFinish | None:
    """将 SurfaceFinishSymbol 对象转为 SWSurfaceFinish。

    API（不同 SolidWorks 版本接口差异较大）：
    - SurfaceFinishSymbol.GetSurfaceFinishValue / GetSymbolType
    - 较新版本：Sw3DPropertyHandler
    - 兜底：尝试多个 getter，失败时仅保留 raw_text
    """
    raw_text: str | None = None
    for method in ("GetText", "GetSurfaceFinishText"):
        try:
            txt = getattr(specific, method)
            if callable(txt):
                txt = txt()
            if txt:
                raw_text = str(txt)
                break
        except Exception:  # noqa: BLE001
            continue

    value_um: float | None = None
    for method in ("GetSurfaceFinishValue", "GetRoughnessValue"):
        try:
            v = getattr(specific, method)
            if callable(v):
                v = v()
            if v not in (None, ""):
                try:
                    value_um = float(v)
                except (TypeError, ValueError):
                    pass
                break
        except Exception:  # noqa: BLE001
            continue

    # 粗糙度类型从 raw_text 推断（Ra/Rz/Rt/Rmax/Rp/Rq）
    roughness_type = "unknown"
    if raw_text:
        for rt in ("Ra", "Rz", "Rmax", "Rt", "Rp", "Rq"):
            if rt in raw_text:
                roughness_type = rt
                break
        else:
            roughness_type = "Ra"  # 缺省假设 Ra

    # 纹理方向：从 raw_text 提取常见方向符号
    direction: str | None = None
    if raw_text:
        for d in ("=", "⊥", "X", "M", "C", "R", "P"):
            if d in raw_text:
                direction = d
                break

    # 加工方法（去除材料要求）：从符号类型推断
    removal_required: bool | None = None
    try:
        sym_type = getattr(specific, "GetSymbolType", None)
        if callable(sym_type):
            sym_type = sym_type()
        if sym_type is not None:
            # swSurfaceFinishSymbolType_e:
            #   0=MachineRequired（需去除材料）
            #   1=NoMachineRequired（不允许去除材料）
            #   2=Any（任意）
            try:
                t = int(sym_type)
                if t == 0:
                    removal_required = True
                elif t == 1:
                    removal_required = False
            except (TypeError, ValueError):
                pass
    except Exception:  # noqa: BLE001
        pass

    attached = None
    try:
        attached = _get_attached_entity_label(anno)
    except Exception:  # noqa: BLE001
        pass

    return SWSurfaceFinish(
        roughness=roughness_type,  # type: ignore[arg-type]
        value=value_um,
        machining_method=None,
        direction=direction,
        removal_required=removal_required,
        raw_text=raw_text,
        attached_entity=attached,
    )


def _convert_note(specific: Any) -> SWTechnicalNote | None:
    """将 Note 对象转为 SWTechnicalNote（SLDDRW 注释，SLDPRT/SLDASM 一般无）。"""
    text: str | None = None
    for method in ("GetText", "GetText2"):
        try:
            t = getattr(specific, method)
            if callable(t):
                t = t()
            if t:
                text = str(t).strip()
                break
        except Exception:  # noqa: BLE001
            continue
    if not text:
        return None
    return _classify_technical_note(text, source="note")


def _get_attached_entity_label(anno: Any) -> str | None:
    """获取注解附加到的实体标识（兜底返回实体计数）。"""
    try:
        attached = anno.GetAttachedEntities()
        if attached is None:
            return None
        try:
            n = len(attached)
        except TypeError:
            n = 1
        if n == 0:
            return None
        return f"attached_entities={n}"
    except Exception:  # noqa: BLE001
        return None


# ===== 自定义属性与技术要求提取 =====


# 已知的技术要求自定义属性键名（中英文常见命名，小写匹配）
_TECH_NOTE_KEYS: set[str] = {
    "技术要求",
    "technicalrequirements",
    "technical requirements",
    "technical_requirement",
    "notes",
    "note",
    "remark",
    "remarks",
    "备注",
    "说明",
}


def _extract_custom_properties(
    doc: Any, session: SolidWorksSession | None = None
) -> list[SWCustomProperty]:
    """提取文件级与配置级自定义属性。

    API（SolidWorks API Help 2025）：
    - ModelDoc2.Extension.CustomPropertyManager(name)：获取指定配置的属性管理器
      name="" 表示文件级
    - CustomPropertyManager.GetNames：属性名数组
    - Get5/Get4/Get2/Get 兼容多版本（pywin32 无法直接传 ByRef，
      优先 Get5 返回元组）

    实现覆盖：文件级 + 各配置级（通过 GetConfigurationNames 获取配置列表）
    """
    props: list[SWCustomProperty] = []
    # 强类型路径：包装 doc 为 IModelDoc2
    sw_module = _get_typelib_module(session) if session else None
    if sw_module is not None:
        doc = _wrap_as_imodeldoc2(doc, sw_module)
    try:
        ext = doc.Extension
    except Exception:  # noqa: BLE001
        return props

    # 文件级 + 各配置级
    configs_to_query: list[str | None] = [None]  # None 表示文件级
    try:
        config_names = doc.GetConfigurationNames()
        if config_names:
            for name in config_names:
                configs_to_query.append(str(name))
    except Exception:  # noqa: BLE001
        pass

    seen: set[tuple[str | None, str]] = set()
    for cfg in configs_to_query:
        try:
            cpm = ext.CustomPropertyManager(cfg if cfg else "")
        except Exception:  # noqa: BLE001
            continue
        if cpm is None:
            continue
        try:
            names = cpm.GetNames()
        except Exception:  # noqa: BLE001
            names = None
        if not names:
            continue
        try:
            name_list = list(names)
        except TypeError:
            name_list = [names]
        for pname in name_list:
            if not pname:
                continue
            pname_str = str(pname)
            key = (cfg, pname_str)
            if key in seen:
                continue
            seen.add(key)
            value = _get_custom_property_value(cpm, pname_str)
            if value is None:
                continue
            props.append(
                SWCustomProperty(
                    name=pname_str,
                    value=value,
                    configuration=cfg,
                )
            )
    return props


def _get_custom_property_value(cpm: Any, name: str) -> str | None:
    """从 CustomPropertyManager 获取属性值（兼容多版本接口）。

    优先级（从新到旧）：
    1. Get5(name, useCached) → 返回 (resolved, valOut, wasResolved)
    2. Get4(name, useCached) → 返回 (valOut, resolved)
    3. Get2(name, useCached) → pywin32 通常仅返回 valOut
    4. Get(name) → 仅返回 valOut（最旧）
    """
    for method_name in ("Get5", "Get4", "Get2", "Get"):
        method = getattr(cpm, method_name, None)
        if method is None:
            continue
        try:
            if method_name in ("Get5", "Get4", "Get2"):
                result = method(name, False)
            else:
                result = method(name)
            if result is None:
                continue
            if isinstance(result, (tuple, list)):
                for item in result:
                    if isinstance(item, str) and item:
                        return item
                continue
            if isinstance(result, str) and result:
                return result
        except Exception:  # noqa: BLE001
            continue
    return None


def _extract_technical_notes_from_props(
    doc: Any, session: SolidWorksSession | None = None
) -> list[SWTechnicalNote]:
    """从已知键名的自定义属性中提取技术要求文本。

    依据 schema 注释：SLDPRT/SLDASM 的技术要求通常存储在自定义属性中。
    键名匹配（不区分大小写）：
    - 技术要求 / TechnicalRequirements / Notes / 备注 等
    """
    notes: list[SWTechnicalNote] = []
    # 强类型路径：包装 doc 为 IModelDoc2
    sw_module = _get_typelib_module(session) if session else None
    if sw_module is not None:
        doc = _wrap_as_imodeldoc2(doc, sw_module)
    try:
        ext = doc.Extension
    except Exception:  # noqa: BLE001
        return notes

    configs_to_query: list[str | None] = [None]
    try:
        config_names = doc.GetConfigurationNames()
        if config_names:
            for name in config_names:
                configs_to_query.append(str(name))
    except Exception:  # noqa: BLE001
        pass

    for cfg in configs_to_query:
        try:
            cpm = ext.CustomPropertyManager(cfg if cfg else "")
        except Exception:  # noqa: BLE001
            continue
        if cpm is None:
            continue
        try:
            names = cpm.GetNames()
        except Exception:  # noqa: BLE001
            names = None
        if not names:
            continue
        try:
            name_list = list(names)
        except TypeError:
            name_list = [names]
        for pname in name_list:
            if not pname:
                continue
            pname_str = str(pname)
            if pname_str.lower() not in _TECH_NOTE_KEYS:
                continue
            value = _get_custom_property_value(cpm, pname_str)
            if not value:
                continue
            # 一个属性可能含多条技术要求（换行分隔）
            for line in value.split("\n"):
                line = line.strip()
                if not line:
                    continue
                note = _classify_technical_note(line, source="custom_property")
                notes.append(note)
    return notes


def _classify_technical_note(
    text: str, source: str = "unknown"
) -> SWTechnicalNote:
    """根据文本特征分类技术要求（一般/热处理/表面处理/机械加工/检验/装配）。"""
    lower = text.lower()
    category: str = "general"
    if any(kw in text for kw in ("淬火", "回火", "退火", "正火", "调质", "渗碳", "氮化",
                                  "热处理", "heat treat", "hardened", "annealed")):
        category = "heat_treat"
    elif any(kw in text for kw in ("镀", "氧化", "发黑", "磷化", "喷涂", "漆",
                                    "表面处理", "anodized", "plated", "coated")):
        category = "surface_treat"
    elif any(kw in text for kw in ("铣", "车", "磨", "镗", "钻", "铰", "加工",
                                    "倒角", "圆角", "machining", "milled", "turned")):
        category = "machining"
    elif any(kw in text for kw in ("检验", "探伤", "测量", "inspection",
                                    "test", "verify")):
        category = "inspection"
    elif any(kw in text for kw in ("装配", "安装", "拧紧", "扭矩", "assembly",
                                    "install", "torque")):
        category = "assembly"
    elif "general" in lower or "一般" in text:
        category = "general"
    return SWTechnicalNote(
        category=category,  # type: ignore[arg-type]
        text=text,
        source=source,  # type: ignore[arg-type]
    )


# ===== 质量属性提取 =====


def _extract_mass_properties(
    doc: Any, session: SolidWorksSession | None = None
) -> SWMassProperty | None:
    """提取质量属性（质量/体积/表面积/重心/惯性矩）。

    API（SolidWorks API Help 2025）：
    - ModelDoc2.Extension.GetMassProperties(accuracy)：
      返回 array[12]：[mass, volume, com_x, com_y, com_z,
                       xx, yy, zz, xy, yz, zx, status]
      单位：随文档单位系统（MMGS=mm-g-s / IPS=in-lb-s / MKS=m-kg-s）
      accuracy: 1.0 表示默认精度
    - 状态码：0=成功, 1=失败, 2=未分配材料
    """
    # 强类型路径：包装 doc 为 IModelDoc2
    sw_module = _get_typelib_module(session) if session else None
    if sw_module is not None:
        doc = _wrap_as_imodeldoc2(doc, sw_module)
    try:
        ext = doc.Extension
    except Exception:  # noqa: BLE001
        return None
    try:
        # GetMassProperties(accuracy, status) - status 是 ByRef out 参数
        # 强类型接口：传 0 即可（类型库自动处理 ByRef）
        # 动态 Dispatch：返回值可能直接是数组或带 status 的 tuple
        if sw_module is not None:
            result = ext.GetMassProperties(1.0, 0)
        else:
            result = ext.GetMassProperties(1.0)
    except Exception as e:  # noqa: BLE001
        log.debug("sw.reader.mass_props_failed", error=str(e))
        return None
    if not result:
        return None
    # 强类型 GetMassProperties 可能返回 (array, status) tuple
    # 动态 Dispatch 通常返回纯数组
    if isinstance(result, tuple) and len(result) == 2 and not isinstance(result[0], (int, float)):
        # 强类型返回 (array, status)
        arr_data = result[0]
        status = result[1]
    else:
        arr_data = result
        status = 0
    try:
        arr = list(arr_data)
    except TypeError:
        arr = [arr_data]
    if len(arr) < 5:
        return None
    # 状态码：0=成功, 1=失败, 2=未分配材料
    try:
        status_int = int(status)
        if status_int == 1:
            log.debug("sw.reader.mass_props_failed", status="failed")
            return None
    except (TypeError, ValueError):
        pass

    # 单位系统检测
    unit_sys = _detect_unit_system(doc)
    length_scale, _mass_scale = _get_unit_scales(unit_sys)

    try:
        mass = float(arr[0]) if arr[0] else None
    except (TypeError, ValueError):
        mass = None
    try:
        volume_raw = float(arr[1]) if arr[1] else None
    except (TypeError, ValueError):
        volume_raw = None
    try:
        com_x = float(arr[2]) if arr[2] else 0.0
        com_y = float(arr[3]) if arr[3] else 0.0
        com_z = float(arr[4]) if arr[4] else 0.0
    except (TypeError, ValueError):
        com_x = com_y = com_z = 0.0

    # 转换为统一单位（mm / kg）
    # API 返回的 mass 始终为 kg（与单位系统无关）
    mass_kg = mass if mass is not None else None
    volume_mm3 = volume_raw * (length_scale ** 3) if volume_raw is not None else None
    com_mm = (
        com_x * length_scale,
        com_y * length_scale,
        com_z * length_scale,
    )

    # 表面积通过 GetMassProperties2 获取（如可用）
    surface_area_mm2: float | None = None
    try:
        mp2 = getattr(ext, "GetMassProperties2", None)
        if callable(mp2):
            r2 = mp2(1.0, 1)  # accuracy=1.0, status flag
            if r2 and len(list(r2)) > 12:
                # 第 13 项为表面积（部分版本）
                try:
                    sa_raw = float(list(r2)[12])
                    surface_area_mm2 = sa_raw * (length_scale ** 2)
                except (TypeError, ValueError, IndexError):
                    pass
    except Exception:  # noqa: BLE001
        pass

    # 主惯性轴与主惯性矩：SolidWorks API 不直接提供，
    # inertia array（arr[5:11]）为惯性张量，需后续协方差分解
    # 此处仅保留 None，下游审图按需扩展
    return SWMassProperty(
        mass=mass_kg,
        volume=volume_mm3,
        surface_area=surface_area_mm2,
        center_of_mass=com_mm,
        principal_axes=None,
        principal_moments=None,
    )


def _detect_unit_system(doc: Any) -> str:
    """检测文档单位系统（MMGS/IPSI/MKS/Custom）。

    API：ModelDoc2.GetUserPreferenceIntegerValue(13) → swUnitSystem_e
    - 0 = Custom
    - 1 = MKS（m-kg-s）
    - 2 = MMGS（mm-g-s，默认）
    - 3 = IPS（in-lb-s）
    """
    try:
        sys_enum = doc.GetUserPreferenceIntegerValue(13)
        mapping = {0: "custom", 1: "mks", 2: "mmgs", 3: "ips"}
        return mapping.get(int(sys_enum), "mmgs")
    except Exception:  # noqa: BLE001
        return "mmgs"


def _get_unit_scales(unit_sys: str) -> tuple[float, float]:
    """返回 (length_scale_to_mm, mass_scale_to_kg)。

    用于 GetMassProperties 返回值到统一 mm/kg 的换算。
    """
    if unit_sys == "mks":
        return 1000.0, 1.0  # m → mm；kg → kg
    if unit_sys == "ips":
        return 25.4, 0.45359237  # in → mm；lb → kg
    # MMGS / custom 兜底：mm & g
    return 1.0, 0.001  # mm → mm；g → kg


# ===== 装配体专用提取（组件 / 配合 / BOM）=====


def _extract_components(
    doc: Any, session: SolidWorksSession | None = None
) -> list[SWComponent]:
    """递归提取装配体顶层组件（含子组件嵌套）。

    API：
    - AssemblyDoc.GetComponents(topLevelOnly)：
      topLevelOnly=True 仅返回顶层；False 返回全部（含子装配体内部）
      本函数取顶层 + 通过 Component2.GetChildren 递归
    - Component2.Name2：组件名（如 "法兰盘-1"）
    - Component2.GetPathName：引用文件路径
    - Component2.ReferencedConfiguration：引用配置
    - Component2.IsSuppressed：是否被压缩
    - Component2.GetChildren：子组件数组
    - Component2.Transform2：4×4 变换矩阵
    """
    components: list[SWComponent] = []
    # 强类型路径：包装 doc 为 IAssemblyDoc（若可用），否则 IModelDoc2
    sw_module = _get_typelib_module(session) if session else None
    if sw_module is not None:
        # 尝试 IAssemblyDoc 包装（GetComponents 是其方法）
        if hasattr(sw_module, "IAssemblyDoc"):
            try:
                doc = sw_module.IAssemblyDoc(doc._oleobj_) if hasattr(doc, "_oleobj_") else doc
            except Exception:  # noqa: BLE001
                doc = _wrap_as_imodeldoc2(doc, sw_module)
        else:
            doc = _wrap_as_imodeldoc2(doc, sw_module)
    try:
        comps = doc.GetComponents(True)  # topLevelOnly=True
    except Exception as e:  # noqa: BLE001
        log.warning("sw.reader.get_components_failed", error=str(e))
        return components
    if not comps:
        return components
    try:
        comp_list = list(comps)
    except TypeError:
        comp_list = [comps]
    for comp in comp_list:
        if comp is None:
            continue
        sw_comp = _convert_component(comp)
        if sw_comp is not None:
            components.append(sw_comp)
    return components


def _convert_component(comp: Any) -> SWComponent | None:
    """将 Component2 转为 SWComponent（递归子组件）。"""
    name: str | None = None
    try:
        name = str(comp.Name2)
    except Exception:  # noqa: BLE001
        return None
    source_file: str | None = None
    try:
        source_file = str(comp.GetPathName())
    except Exception:  # noqa: BLE001
        pass
    configuration: str | None = None
    try:
        configuration = str(comp.ReferencedConfiguration)
    except Exception:  # noqa: BLE001
        pass
    is_suppressed = False
    try:
        is_suppressed = bool(comp.IsSuppressed())
    except Exception:  # noqa: BLE001
        pass
    is_flexible = False
    try:
        # GetFlexibilityStatus 较新接口，不可用时默认 False
        flex = comp.GetFlexibilityStatus
        if callable(flex):
            flex = flex()
        if flex:
            is_flexible = bool(int(flex))
    except Exception:  # noqa: BLE001
        pass
    # 实例号：从名称末尾 "-N" 提取
    instance_id = 1
    if name and "-" in name:
        try:
            tail = name.rsplit("-", 1)[-1]
            instance_id = int(tail)
        except ValueError:
            pass
    # 4×4 变换矩阵（行主序 16 个 double）
    transform: list[float] | None = None
    try:
        tf = comp.Transform2
        if callable(tf):
            tf = tf()
        if tf is not None:
            # MathTransform.ArrayData 返回 16 个 double（4×4 行主序）
            arr_data = None
            for m in ("ArrayData", "ArrayData2"):
                ad = getattr(tf, m, None)
                if callable(ad):
                    ad = ad()
                if ad is not None:
                    arr_data = ad
                    break
            if arr_data:
                try:
                    transform = [float(x) for x in list(arr_data)[:16]]
                except (TypeError, ValueError):
                    transform = None
    except Exception:  # noqa: BLE001
        pass

    # 递归子组件
    children: list[SWComponent] = []
    try:
        # 强类型 IComponent2 中 GetChildren 可能是属性（返回 tuple），
        # 动态 Dispatch 中是方法（需调用）。
        sub_comps = comp.GetChildren
        if callable(sub_comps):
            sub_comps = sub_comps()
        if sub_comps:
            try:
                sub_list = list(sub_comps)
            except TypeError:
                sub_list = [sub_comps]
            for sc in sub_list:
                if sc is None:
                    continue
                sw_sc = _convert_component(sc)
                if sw_sc is not None:
                    children.append(sw_sc)
    except Exception as e:  # noqa: BLE001
        log.debug("sw.reader.subcomponent_traverse_failed",
                  component=name, error=str(e))

    return SWComponent(
        name=name,
        source_file=source_file,
        configuration=configuration,
        instance_id=instance_id,
        is_suppressed=is_suppressed,
        is_flexible=is_flexible,
        transform=transform,
        children=children,
    )


# swMateType_e → MateType 映射
_MATE_TYPE_MAP: dict[int, str] = {
    _SW_MATE_COINCIDENT: "coincident",
    _SW_MATE_CONCENTRIC: "concentric",
    _SW_MATE_PERPENDICULAR: "perpendicular",
    _SW_MATE_PARALLEL: "parallel",
    _SW_MATE_TANGENT: "tangent",
    _SW_MATE_DISTANCE: "distance",
    _SW_MATE_ANGLE: "angle",
    _SW_MATE_SYMMETRIC: "unknown",  # schema 无 symmetric，归 unknown
    _SW_MATE_CAM: "cam",
    _SW_MATE_GEAR: "gear",
    _SW_MATE_UNIVERSAL_JOINT: "universal_joint",
    _SW_MATE_RACK_PINION: "rack_pinion",
    _SW_MATE_LINEAR_COUPLER: "linear_coupler",
    _SW_MATE_PATH: "path",
    _SW_MATE_LOCK: "lock",
    _SW_MATE_LOCK_TOGETHER: "lock",
    _SW_MATE_SCREW: "screw",
    _SW_MATE_HINGE: "hinge",
    _SW_MATE_SLOT: "slot",
    _SW_MATE_WIDTH: "width",
    _SW_MATE_UNKNOWN: "unknown",
}

# swMateAlign_e
_SW_MATE_ALIGN_ALIGNED = 0
_SW_MATE_ALIGN_ANTI_ALIGNED = 1
_SW_MATE_ALIGN_CLOSEST = 2


def _extract_mates(
    doc: Any, session: SolidWorksSession | None = None
) -> list[SWMate]:
    """提取装配体配合。

    API（多路径兜底）：
    - 路径 1：AssemblyDoc.GetMates()（旧版 API，部分版本可用）
    - 路径 2：遍历特征树，查找 type_name 为 "Mate" 的特征
      （SolidWorks 2025 中 GetMates 已从 IAssemblyDoc 类型库移除，
       需通过特征树遍历获取）

    Mate2 API：
    - Mate2.Name：配合名
    - Mate2.Type：swMateType_e
    - Mate2.MateEntity(idx)：配合实体（0/1）
    - MateEntity2.Component：所属组件
    - Mate2.Distance / Angle：距离/角度配合的数值
    - Mate2.Alignment：swMateAlign_e
    - Mate2.IsSuppressed：是否被压缩
    """
    mates: list[SWMate] = []
    # 强类型路径：包装 doc 为 IAssemblyDoc（用于 GetComponents 等方法）
    sw_module = _get_typelib_module(session) if session else None
    if sw_module is not None and hasattr(sw_module, "IAssemblyDoc"):
        try:
            asm_doc = sw_module.IAssemblyDoc(doc._oleobj_) if hasattr(doc, "_oleobj_") else doc
        except Exception:  # noqa: BLE001
            asm_doc = doc
    else:
        asm_doc = doc

    # 路径 1：尝试 GetMates（旧版 API，部分版本可用）
    mate_arr = None
    try:
        if hasattr(asm_doc, "GetMates"):
            mate_arr = asm_doc.GetMates
            if callable(mate_arr):
                mate_arr = mate_arr()
    except Exception as e:  # noqa: BLE001
        log.debug("sw.reader.get_mates_method_failed", error=str(e))
        mate_arr = None

    if mate_arr:
        try:
            mate_list = list(mate_arr)
        except TypeError:
            mate_list = [mate_arr]
        for mate in mate_list:
            if mate is None:
                continue
            sw_mate = _convert_mate(mate)
            if sw_mate is not None:
                mates.append(sw_mate)
        if mates:
            return mates

    # 路径 2：遍历特征树查找 Mate 特征
    # SolidWorks 2025 中配合以 "Mate" 类型特征存储在特征树中
    try:
        # 用 IModelDoc2 包装以调用 FirstFeature
        model_doc = _wrap_as_imodeldoc2(doc, sw_module) if sw_module is not None else doc
        feat = None
        if sw_module is not None:
            try:
                feat = model_doc.FirstFeature()
            except Exception:  # noqa: BLE001
                feat = None
        else:
            try:
                feat = model_doc.GetFirstFeature()
            except Exception:  # noqa: BLE001
                feat = None

        while feat is not None:
            feat = _wrap_as_ifeature(feat, sw_module)
            try:
                type_name = str(feat.GetTypeName2())
                # 配合特征的类型名
                if type_name in ("Mate", "MateGroup", "LocalMateFolder"):
                    # 从配合特征获取具体的 Mate2 对象
                    try:
                        specific = feat.GetSpecificFeature2()
                        if specific is not None:
                            # MateGroup 可能包含多个 Mate
                            if type_name == "MateGroup":
                                # 遍历子特征获取每个 Mate
                                sub_feat = feat.GetFirstSubFeature()
                                while sub_feat is not None:
                                    sub_feat = _wrap_as_ifeature(sub_feat, sw_module)
                                    try:
                                        sub_type = str(sub_feat.GetTypeName2())
                                        if sub_type == "Mate":
                                            sub_specific = sub_feat.GetSpecificFeature2()
                                            if sub_specific is not None:
                                                sw_mate = _convert_mate(sub_specific)
                                                if sw_mate is not None:
                                                    mates.append(sw_mate)
                                    except Exception:  # noqa: BLE001
                                        pass
                                    try:
                                        sub_feat = sub_feat.GetNextSubFeature()
                                    except Exception:  # noqa: BLE001
                                        break
                            else:
                                # 单个 Mate 特征
                                sw_mate = _convert_mate(specific)
                                if sw_mate is not None:
                                    mates.append(sw_mate)
                    except Exception as e:  # noqa: BLE001
                        log.debug("sw.reader.mate_specific_failed",
                                  type=type_name, error=str(e))
            except Exception:  # noqa: BLE001
                pass
            try:
                feat = feat.GetNextFeature()
            except Exception as e:  # noqa: BLE001
                log.debug("sw.reader.mate_next_feature_failed", error=str(e))
                break
    except Exception as e:  # noqa: BLE001
        log.warning("sw.reader.mates_traverse_failed", error=str(e))

    if not mates:
        log.info("sw.reader.no_mates_found",
                 detail="装配体无配合特征或 GetMates API 不可用")
    return mates


def _convert_mate(mate: Any) -> SWMate | None:
    """将 Mate2 转为 SWMate。"""
    name: str | None = None
    try:
        name = str(mate.Name)
    except Exception:  # noqa: BLE001
        return None
    type_enum = _SW_MATE_UNKNOWN
    try:
        type_enum = int(mate.Type)
    except Exception:  # noqa: BLE001
        pass
    mate_type = _MATE_TYPE_MAP.get(type_enum, "unknown")

    is_suppressed = False
    try:
        is_suppressed = bool(mate.IsSuppressed())
    except Exception:  # noqa: BLE001
        pass

    # 两个配合实体
    comp1, comp2, ent1, ent2 = _get_mate_entities(mate)

    # 距离/角度配合数值（distance 字段复用为统一数值字段）
    distance: float | None = None
    if mate_type == "distance":
        try:
            d_raw = float(mate.Distance)
            # API 返回值随文档单位系统（m 或 mm 或 in），统一转 mm
            unit_sys = _detect_unit_system_from_doc(mate)
            length_scale, _ = _get_unit_scales(unit_sys)
            distance = d_raw * length_scale if length_scale != 1.0 else d_raw
        except Exception:  # noqa: BLE001
            pass
    elif mate_type == "angle":
        try:
            a_raw = float(mate.Angle)
            # API 返回弧度，转度
            distance = math.degrees(a_raw)
        except Exception:  # noqa: BLE001
            pass

    alignment = "unknown"
    try:
        align_enum = int(mate.Alignment)
        if align_enum == _SW_MATE_ALIGN_ALIGNED:
            alignment = "aligned"
        elif align_enum == _SW_MATE_ALIGN_ANTI_ALIGNED:
            alignment = "anti_aligned"
        elif align_enum == _SW_MATE_ALIGN_CLOSEST:
            alignment = "none"
    except Exception:  # noqa: BLE001
        pass

    return SWMate(
        name=name,
        type=mate_type,  # type: ignore[arg-type]
        is_suppressed=is_suppressed,
        component_1=comp1,
        component_2=comp2,
        entity_1=ent1,
        entity_2=ent2,
        distance=distance,
        alignment=alignment,  # type: ignore[arg-type]
    )


def _get_mate_entities(
    mate: Any,
) -> tuple[str | None, str | None, str | None, str | None]:
    """获取配合的两个实体（组件名 + 实体类型标识）。

    API（经 SolidWorks API Help 2026 官方示例核对）：
    - Mate2.MateEntity(idx)：MateEntity2 对象
      来源：https://help.solidworks.com/2026/english/api/sldworksapi/Get_Mates_and_Mate_Entities_Example_VB.htm
    - MateEntity2.ReferenceComponent：Component2 对象（官方属性名）
    - MateEntity2.ReferenceType：swMateEntityTypes_e（官方属性名）
      0=face, 1=edge, 2=vertex, 3=axis, 4=plane, ...

    注意：早期代码误用 me.Component / me.EntityType（非官方属性名），
    已根据官方 VBA 示例修正为 ReferenceComponent / ReferenceType。
    保留 try/except 兜底以兼容版本差异。
    """
    comp1 = comp2 = ent1 = ent2 = None
    for idx, slot in enumerate((0, 1)):
        try:
            me = mate.MateEntity(idx)
        except Exception:  # noqa: BLE001
            continue
        if me is None:
            continue
        comp_name: str | None = None
        try:
            # 官方属性名：ReferenceComponent
            comp_obj = me.ReferenceComponent
            if comp_obj is not None:
                comp_name = str(comp_obj.Name2)
        except Exception:  # noqa: BLE001
            pass
        ent_label: str | None = None
        try:
            # 官方属性名：ReferenceType（swMateEntityTypes_e）
            ent_type = int(me.ReferenceType)
            type_map = {
                0: "face", 1: "edge", 2: "vertex",
                3: "axis", 4: "plane", 5: "point",
            }
            ent_label = type_map.get(ent_type, f"entity_type_{ent_type}")
        except Exception:  # noqa: BLE001
            ent_label = "unknown"
        if slot == 0:
            comp1, ent1 = comp_name, ent_label
        else:
            comp2, ent2 = comp_name, ent_label
    return comp1, comp2, ent1, ent2


def _detect_unit_system_from_doc(obj: Any) -> str:
    """从配合对象反查文档单位系统（兜底 MMGS）。"""
    try:
        doc = obj.GetDocument
        if callable(doc):
            doc = doc()
        if doc is not None:
            return _detect_unit_system(doc)
    except Exception:  # noqa: BLE001
        pass
    return "mmgs"


# ===== BOM 明细栏提取 =====


def _extract_bom(
    doc: Any, session: SolidWorksSession | None = None
) -> list[SWBOMItem]:
    """提取装配体 BOM 明细栏。

    实现策略（优先级递降）：
    1. **基于组件遍历**（最可靠，与 SolidWorks 版本无关）：
       遍历装配体所有组件，从组件引用文件的自定义属性提取
       件号/图号/材料/质量等
    2. **基于 BOM 表特征**（备选，未实现）：
       AssemblyDoc.FeatureManager.GetBomFeatures() → BOM 表特征
       TableAnnotation.GetRowCount / GetText(row, col) → 单元格文本

    本实现采用策略 1（与下游审图模块对结构化数据的需求最匹配）。
    """
    bom_items: list[SWBOMItem] = []
    # 强类型路径：包装 doc 为 IAssemblyDoc
    sw_module = _get_typelib_module(session) if session else None
    if sw_module is not None and hasattr(sw_module, "IAssemblyDoc"):
        try:
            doc = sw_module.IAssemblyDoc(doc._oleobj_) if hasattr(doc, "_oleobj_") else doc
        except Exception:  # noqa: BLE001
            pass
    try:
        comps = doc.GetComponents(False)  # 全部组件（含子装配）
    except Exception as e:  # noqa: BLE001
        log.warning("sw.reader.bom_get_components_failed", error=str(e))
        return bom_items
    if not comps:
        return bom_items
    try:
        comp_list = list(comps)
    except TypeError:
        comp_list = [comps]

    item_no = 0
    seen_paths: set[str] = set()
    for comp in comp_list:
        if comp is None:
            continue
        item_no += 1
        item = _convert_bom_item(comp, item_no)
        if item is None:
            continue
        # 同一引用文件去重（保留首次出现，数量累加）
        key = (item.source_file or "").lower()
        if key and key in seen_paths:
            for existing in bom_items:
                existing_key = (existing.source_file or "").lower()
                if existing_key == key:
                    existing.quantity += 1
                    if existing.total_mass is not None and existing.mass is not None:
                        existing.total_mass = existing.mass * existing.quantity
                    item_no -= 1  # 不占用新件号
                    break
            continue
        seen_paths.add(key)
        bom_items.append(item)
    return bom_items


def _convert_bom_item(comp: Any, item_no: int) -> SWBOMItem | None:
    """将单个组件转为 BOM 项（从引用文件自定义属性提取元数据）。"""
    name: str | None = None
    try:
        name = str(comp.Name2)
    except Exception:  # noqa: BLE001
        return None
    source_file: str | None = None
    try:
        source_file = str(comp.GetPathName())
    except Exception:  # noqa: BLE001
        pass
    configuration: str | None = None
    try:
        configuration = str(comp.ReferencedConfiguration)
    except Exception:  # noqa: BLE001
        pass

    # 从组件引用文件获取自定义属性（件号/图号/材料/质量等）
    custom_props: dict[str, str] = {}
    try:
        comp_model = comp.GetModelDoc2()
        if comp_model is not None:
            try:
                ext = comp_model.Extension
                cpm = ext.CustomPropertyManager("")
                if cpm is not None:
                    names = cpm.GetNames()
                    if names:
                        try:
                            name_list = list(names)
                        except TypeError:
                            name_list = [names]
                        for pname in name_list:
                            if not pname:
                                continue
                            pname_str = str(pname)
                            value = _get_custom_property_value(cpm, pname_str)
                            if value:
                                custom_props[pname_str] = value
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass

    # 从自定义属性映射常见 BOM 字段（中英文键名兼容）
    part_number = (
        custom_props.get("PartNumber")
        or custom_props.get("零件号")
        or custom_props.get("图号")
        or custom_props.get("DrawingNumber")
        or custom_props.get("代号")
    )
    description = (
        custom_props.get("Description")
        or custom_props.get("描述")
        or custom_props.get("名称")
        or custom_props.get("Title")
        or custom_props.get("名称 1")
        or name
    )
    material = (
        custom_props.get("Material")
        or custom_props.get("材料")
        or custom_props.get("材质")
        or custom_props.get("MaterialName")
    )
    mass: float | None = None
    mass_str = (
        custom_props.get("Mass")
        or custom_props.get("质量")
        or custom_props.get("Weight")
    )
    if mass_str:
        try:
            mass = float(mass_str)
        except ValueError:
            mass = None

    total_mass = mass if mass is not None else None

    return SWBOMItem(
        item_number=item_no,
        part_number=part_number,
        description=description,
        quantity=1,
        material=material,
        mass=mass,
        total_mass=total_mass,
        configuration=configuration,
        source_file=source_file,
        custom_properties=custom_props,
    )


# ===== 模块自检入口（不依赖 SolidWorks 实例）=====


def _self_test() -> dict[str, Any]:
    """离线自检：验证模块导入与 schema 依赖完整。

    本函数不调用 SolidWorks API，可在 Linux 环境运行。
    用于 CI / 离线环境验证模块完整性。

    Returns:
        {"ok": bool, "errors": list[str], "checks": dict[str, bool]}
    """
    checks: dict[str, bool] = {}
    errors: list[str] = []
    try:
        from app.schemas.solidworks_model import SolidWorksModel  # noqa: F401
        checks["schema_import"] = True
    except Exception as e:  # noqa: BLE001
        checks["schema_import"] = False
        errors.append(f"schema 导入失败: {e}")
    try:
        from app.services.solidworks.sw_session import (  # noqa: F401
            is_solidworks_available,
        )
        checks["session_import"] = True
        # Linux 下应返回 False，Windows+pywin32 下返回 True
        checks["available_flag"] = isinstance(is_solidworks_available(), bool)
    except Exception as e:  # noqa: BLE001
        checks["session_import"] = False
        errors.append(f"session 导入失败: {e}")
    try:
        from app.services.solidworks.worker_pool import (  # noqa: F401
            solidworks_task,
        )
        checks["worker_pool_import"] = True
    except Exception as e:  # noqa: BLE001
        checks["worker_pool_import"] = False
        errors.append(f"worker_pool 导入失败: {e}")
    try:
        # 验证常量映射表完整
        checks["feature_type_map"] = len(_FEATURE_TYPE_MAP) > 0
        checks["mate_type_map"] = len(_MATE_TYPE_MAP) > 0
        checks["gtol_symbol_map"] = len(_GTOL_SYMBOL_MAP) > 0
        checks["tolerance_map"] = _SW_TOL_BILAT > 0
    except Exception as e:  # noqa: BLE001
        checks["constants"] = False
        errors.append(f"常量映射校验失败: {e}")
    # 公共入口函数签名验证
    checks["read_sldprt_callable"] = callable(read_sldprt)
    checks["read_sldasm_callable"] = callable(read_sldasm)

    ok = all(checks.values())
    return {"ok": ok, "errors": errors, "checks": checks}


if __name__ == "__main__":  # pragma: no cover
    import json

    result = _self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    import sys
    sys.exit(0 if result["ok"] else 1)
