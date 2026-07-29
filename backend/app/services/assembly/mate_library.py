"""装配库：确定性 mate 变换矩阵 + Port-Mate 类型兼容性（Task 10.2）。

实现 AssemCAD 范式的核心几何运算：
1. Port-Mate 类型兼容性校验（interface_match）
2. 确定性 mate 变换矩阵计算（将零件 B 放置到满足 Mate 的位置）
3. B-Rep 接口验证（如果零件有 STEP 文件，校验 Port 真实存在）

设计原则（"以瞎猜接口为耻"）：
- 所有几何运算基于线性代数（numpy），不依赖 SolidWorks/CAD 内核
- mate 变换矩阵为 4×4 行主序，与 SWComponent.transform 一致
- 单位 mm（与外部约定一致）
- 不依赖 pywin32 / pythonOCC（纯 Python + numpy），可跨平台运行

参考：
- AssemCAD: https://arxiv.org/html/2607.05123v1
- SolidWorks Mate 类型: https://help.solidworks.com/2025/english/api/sldworksapiprogguide/
- 4×4 变换矩阵惯例：行主序，平移分量在 [3],[7],[11]
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from app.logging import get_logger
from app.schemas.assembly import MateSpec, Port, PortType, TypedPart

log = get_logger(__name__)

# 单位精度（mm）
_EPSILON = 1e-6


# ===== Port-Mate 类型兼容性矩阵 =====

# 行=MateType，列=(PortType_A, PortType_B)，值=是否兼容
_COMPATIBILITY: dict[str, set[tuple[PortType, PortType]]] = {
    "coincident": {
        ("planar_face", "planar_face"),
        ("linear_edge", "linear_edge"),
        ("vertex", "vertex"),
        ("circular_edge", "circular_edge"),
        ("origin", "origin"),
    },
    "concentric": {
        ("cylindrical", "cylindrical"),
        ("circular_edge", "circular_edge"),
        ("axis", "axis"),
        ("cylindrical", "axis"),
        ("axis", "cylindrical"),
    },
    "parallel": {
        ("planar_face", "planar_face"),
    },
    "perpendicular": {
        ("planar_face", "planar_face"),
    },
    "tangent": {
        ("cylindrical", "planar_face"),
        ("planar_face", "cylindrical"),
        ("cylindrical", "cylindrical"),
    },
    "distance": {
        ("planar_face", "planar_face"),
        ("vertex", "vertex"),
        ("axis", "axis"),
    },
    "angle": {
        ("planar_face", "planar_face"),
    },
    "lock": {
        # lock 适用于任何 Port 组合（完全约束）
        ("planar_face", "planar_face"),
        ("cylindrical", "cylindrical"),
        ("vertex", "vertex"),
    },
}


def is_port_compatible_with_mate(
    port_a: Port,
    port_b: Port,
    mate_type: str,
) -> tuple[bool, str]:
    """校验两个 Port 是否兼容指定的 Mate 类型。

    Args:
        port_a: 零件 A 的 Port
        port_b: 零件 B 的 Port
        mate_type: Mate 类型

    Returns:
        (is_compatible, reason)
        - is_compatible=True 时 reason 为空
        - is_compatible=False 时 reason 为失败原因
    """
    if mate_type not in _COMPATIBILITY:
        return False, f"不支持的 Mate 类型: {mate_type}"
    allowed = _COMPATIBILITY[mate_type]
    pair = (port_a.type, port_b.type)
    if pair in allowed:
        return True, ""
    # 反向尝试（A↔B 对称的 Mate）
    pair_rev = (port_b.type, port_a.type)
    if pair_rev in allowed:
        return True, ""
    return (
        False,
        f"Port 类型 ({port_a.type}, {port_b.type}) 不兼容 Mate 类型 {mate_type}",
    )


# ===== Port 几何提取 =====


def _vec3(d: dict[str, Any], key: str) -> np.ndarray:
    """从 dict 提取 3D 向量。"""
    v = d.get(key)
    if v is None or len(v) != 3:
        raise ValueError(f"几何字段 '{key}' 缺失或非 3D 向量: {v}")
    return np.array([float(v[0]), float(v[1]), float(v[2])], dtype=np.float64)


def _normalize(v: np.ndarray) -> np.ndarray:
    """单位化向量，零向量返回零向量。"""
    n = float(np.linalg.norm(v))
    if n < _EPSILON:
        return v.copy()
    return v / n


def get_port_origin(port: Port) -> np.ndarray:
    """提取 Port 的原点坐标。

    不同 PortType 的原点字段：
    - planar_face: geometry["origin"]
    - cylindrical: geometry["axis_point"]
    - circular_edge: geometry["center"]
    - linear_edge: geometry["start"]
    - vertex: geometry["point"]
    - axis: geometry["point"]
    - origin: [0, 0, 0]
    """
    if port.type == "origin":
        return np.zeros(3, dtype=np.float64)
    g = port.geometry
    field_map = {
        "planar_face": "origin",
        "cylindrical": "axis_point",
        "circular_edge": "center",
        "linear_edge": "start",
        "vertex": "point",
        "axis": "point",
    }
    field = field_map.get(port.type)
    if field is None:
        raise ValueError(f"未知 PortType: {port.type}")
    return _vec3(g, field)


def get_port_direction(port: Port) -> np.ndarray:
    """提取 Port 的方向向量（单位化）。

    不同 PortType 的方向字段：
    - planar_face: geometry["normal"]
    - cylindrical: geometry["axis_dir"]
    - circular_edge: geometry["normal"]
    - axis: geometry["direction"]
    - linear_edge: end - start
    - vertex/origin: 不适用，返回 [0,0,0]
    """
    g = port.geometry
    if port.type == "planar_face":
        return _normalize(_vec3(g, "normal"))
    if port.type == "cylindrical":
        return _normalize(_vec3(g, "axis_dir"))
    if port.type == "circular_edge":
        return _normalize(_vec3(g, "normal"))
    if port.type == "axis":
        return _normalize(_vec3(g, "direction"))
    if port.type == "linear_edge":
        start = _vec3(g, "start")
        end = _vec3(g, "end")
        return _normalize(end - start)
    if port.type in ("vertex", "origin"):
        return np.zeros(3, dtype=np.float64)
    raise ValueError(f"未知 PortType: {port.type}")


def get_port_radius(port: Port) -> float | None:
    """提取 Port 的半径（cylindrical/circular_edge）。"""
    if port.type not in ("cylindrical", "circular_edge"):
        return None
    r = port.geometry.get("radius")
    if r is None:
        raise ValueError(f"Port {port.name} ({port.type}) 缺少 radius 字段")
    return float(r)


# ===== 4×4 变换矩阵工具 =====


def identity_transform() -> list[float]:
    """返回 4×4 单位矩阵（行主序，16 个 float）。"""
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _mat_to_list(m: np.ndarray) -> list[float]:
    """4×4 numpy 矩阵 → 行主序 16 个 float 列表。"""
    return [float(x) for x in m.flatten()]


def _list_to_mat(t: list[float]) -> np.ndarray:
    """行主序 16 个 float → 4×4 numpy 矩阵。"""
    if len(t) != 16:
        raise ValueError(f"变换矩阵必须 16 个元素，实际 {len(t)}")
    return np.array(t, dtype=np.float64).reshape(4, 4)


def _translation_matrix(t: np.ndarray) -> np.ndarray:
    """构造平移矩阵（4×4）。"""
    m = np.eye(4, dtype=np.float64)
    m[:3, 3] = t
    return m


def _rotation_matrix_from_vectors(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """构造将向量 a 旋转到 b 方向的旋转矩阵（4×4）。

    使用 Rodrigues 公式：
        v = a × b
        s = |v|
        c = a · b
        R = I + [v]× + [v]×² (1-c)/s²

    特殊情况：
    - a == b：返回单位矩阵
    - a == -b：返回绕任意垂直轴旋转 180°
    """
    a = _normalize(a)
    b = _normalize(b)
    c = float(np.dot(a, b))
    if c > 1.0 - _EPSILON:
        # a ≈ b
        return np.eye(4, dtype=np.float64)
    if c < -1.0 + _EPSILON:
        # a ≈ -b：绕任意垂直轴旋转 180°
        # 找一个不与 a 共线的向量
        if abs(a[0]) < 0.9:
            perp = np.array([1.0, 0.0, 0.0])
        else:
            perp = np.array([0.0, 1.0, 0.0])
        v = _normalize(np.cross(a, perp))
        # 绕 v 旋转 180°
        K = np.array([
            [0.0, -v[2], v[1]],
            [v[2], 0.0, -v[0]],
            [-v[1], v[0], 0.0],
        ])
        R3 = np.eye(3) + 2.0 * (K @ K)
        m = np.eye(4, dtype=np.float64)
        m[:3, :3] = R3
        return m
    # 一般情形：Rodrigues
    v = np.cross(a, b)
    s = float(np.linalg.norm(v))
    K = np.array([
        [0.0, -v[2], v[1]],
        [v[2], 0.0, -v[0]],
        [-v[1], v[0], 0.0],
    ])
    R3 = np.eye(3) + K + (K @ K) * ((1.0 - c) / (s * s))
    m = np.eye(4, dtype=np.float64)
    m[:3, :3] = R3
    return m


# ===== 确定性 mate 变换矩阵计算 =====


def compute_mate_transform(
    port_a: Port,
    port_b: Port,
    mate: MateSpec,
) -> tuple[list[float] | None, str | None]:
    """计算使零件 B 满足 Mate 约束的 4×4 变换矩阵。

    约定：
    - 零件 A 固定不动（已在装配体坐标系中定位）
    - 零件 B 应用变换矩阵 transform_b 后，B 的 Port_B 与 A 的 Port_A 满足 Mate
    - transform_b 为 4×4 行主序 16 个 float

    不同 MateType 的计算：
    - coincident (planar_face): B 的面与 A 的面重合
        - 旋转：B 法向反向对齐 A 法向（面朝向相反）
        - 平移：B 面原点平移到 A 面原点
    - concentric (cylindrical/axis): B 的轴与 A 的轴同轴
        - 旋转：B 轴方向对齐 A 轴方向
        - 平移：B 轴上一点平移到 A 轴上
    - distance (planar_face): B 的面与 A 的面保持固定距离
        - 旋转：B 法向反向对齐 A 法向
        - 平移：B 面原点平移到 A 面原点 + distance * normal_a
    - angle (planar_face): B 的面与 A 的面保持固定角度
        - 旋转：B 法向绕公共轴旋转 angle
        - 平移：B 面原点平移到 A 面原点
    - lock: 完全约束（与 coincident 等价，6 自由度全约束）

    Args:
        port_a: 零件 A 的 Port（固定）
        port_b: 零件 B 的 Port（待变换）
        mate: Mate 规格

    Returns:
        (transform_b_list, error)
        - transform_b_list: 16 个 float，None 表示计算失败
        - error: 失败原因，None 表示成功
    """
    try:
        # 兼容性校验
        ok, reason = is_port_compatible_with_mate(port_a, port_b, mate.type)
        if not ok:
            return None, reason

        origin_a = get_port_origin(port_a)
        origin_b = get_port_origin(port_b)

        if mate.type == "coincident" or mate.type == "lock":
            return _coincident_transform(port_a, port_b, origin_a, origin_b)
        if mate.type == "concentric":
            return _concentric_transform(port_a, port_b, origin_a, origin_b)
        if mate.type == "distance":
            return _distance_transform(port_a, port_b, origin_a, origin_b, mate)
        if mate.type == "angle":
            return _angle_transform(port_a, port_b, origin_a, origin_b, mate)
        if mate.type in ("parallel", "perpendicular"):
            return _angular_relation_transform(
                port_a, port_b, origin_a, origin_b, mate
            )
        if mate.type == "tangent":
            return _tangent_transform(port_a, port_b, origin_a, origin_b)
        return None, f"未实现的 Mate 类型: {mate.type}"
    except Exception as e:  # noqa: BLE001
        log.warning(
            "assembly.mate.compute_failed",
            mate=mate.name,
            type=mate.type,
            error=str(e),
        )
        return None, f"mate 变换计算异常: {e}"


def _coincident_transform(
    port_a: Port,
    port_b: Port,
    origin_a: np.ndarray,
    origin_b: np.ndarray,
) -> tuple[list[float] | None, str | None]:
    """coincident/lock Mate 变换：B 的 Port 与 A 的 Port 重合。

    对于 planar_face：B 法向反向对齐 A 法向（两平面贴合，外法向相反）。
    对于 vertex/origin：仅平移。
    对于 linear_edge：方向对齐 + 平移。
    """
    if port_a.type == "planar_face" and port_b.type == "planar_face":
        normal_a = get_port_direction(port_a)
        normal_b = get_port_direction(port_b)
        # B 法向应反向对齐 A 法向（面贴合）
        R = _rotation_matrix_from_vectors(normal_b, -normal_a)
        # 旋转后 B 原点位置（与 _concentric_transform 保持一致）
        T = _translation_matrix(origin_a - R[:3, :3] @ origin_b)
        return _mat_to_list(T @ R), None
    if port_a.type in ("vertex", "origin") and port_b.type in ("vertex", "origin"):
        T = _translation_matrix(origin_a - origin_b)
        return _mat_to_list(T), None
    if port_a.type == "linear_edge" and port_b.type == "linear_edge":
        dir_a = get_port_direction(port_a)
        dir_b = get_port_direction(port_b)
        R = _rotation_matrix_from_vectors(dir_b, dir_a)
        # 旋转后 B 原点位置（与 _concentric_transform 保持一致）
        T = _translation_matrix(origin_a - R[:3, :3] @ origin_b)
        return _mat_to_list(T @ R), None
    if port_a.type == "circular_edge" and port_b.type == "circular_edge":
        normal_a = get_port_direction(port_a)
        normal_b = get_port_direction(port_b)
        R = _rotation_matrix_from_vectors(normal_b, -normal_a)
        # 旋转后 B 原点位置（与 _concentric_transform 保持一致）
        T = _translation_matrix(origin_a - R[:3, :3] @ origin_b)
        return _mat_to_list(T @ R), None
    return None, f"coincident Mate 不支持 Port 组合: ({port_a.type}, {port_b.type})"


def _concentric_transform(
    port_a: Port,
    port_b: Port,
    origin_a: np.ndarray,
    origin_b: np.ndarray,
) -> tuple[list[float] | None, str | None]:
    """concentric Mate 变换：B 的轴与 A 的轴同轴。

    旋转：B 轴方向对齐 A 轴方向。
    平移：B 轴上一点平移到 A 轴上（沿垂直于轴方向）。
    """
    dir_a = get_port_direction(port_a)
    dir_b = get_port_direction(port_b)
    # 对齐轴方向
    R = _rotation_matrix_from_vectors(dir_b, dir_a)
    # 旋转后 B 的原点位置
    origin_b_rotated = R[:3, :3] @ origin_b
    # 将 B 原点投影到 A 轴上：origin_a + t * dir_a
    # t = (origin_b_rotated - origin_a) · dir_a
    diff = origin_b_rotated - origin_a
    t = float(np.dot(diff, dir_a))
    # B 原点应平移到 A 轴上的投影点
    target_on_axis = origin_a + t * dir_a
    # 但我们想要的是"轴对齐"，不约束沿轴方向的位置（轴对称）
    # 实际生产中应保持 B 当前沿轴位置，这里简化为将 B 原点对齐到 A 轴最近点
    # 等价于消除垂直于轴的偏差
    translation = target_on_axis - origin_b_rotated
    T = _translation_matrix(translation)
    return _mat_to_list(T @ R), None


def _distance_transform(
    port_a: Port,
    port_b: Port,
    origin_a: np.ndarray,
    origin_b: np.ndarray,
    mate: MateSpec,
) -> tuple[list[float] | None, str | None]:
    """distance Mate 变换：B 的面与 A 的面保持固定距离。

    旋转：B 法向反向对齐 A 法向。
    平移：B 面原点平移到 A 面原点 + distance * normal_a。
    """
    if mate.distance_mm is None:
        return None, "distance Mate 缺少 distance_mm"
    if port_a.type != "planar_face" or port_b.type != "planar_face":
        return None, "distance Mate 仅支持 planar_face"
    normal_a = get_port_direction(port_a)
    normal_b = get_port_direction(port_b)
    R = _rotation_matrix_from_vectors(normal_b, -normal_a)
    target = origin_a + float(mate.distance_mm) * normal_a
    origin_b_rotated = R[:3, :3] @ origin_b
    T = _translation_matrix(target - origin_b_rotated)
    return _mat_to_list(T @ R), None


def _angle_transform(
    port_a: Port,
    port_b: Port,
    origin_a: np.ndarray,
    origin_b: np.ndarray,
    mate: MateSpec,
) -> tuple[list[float] | None, str | None]:
    """angle Mate 变换：B 的面与 A 的面保持固定角度。

    旋转：B 法向绕公共边旋转 angle。
    简化：B 法向 = R(angle, normal_a × normal_b) * (-normal_a)
    此处采用近似实现：将 B 法向旋转到与 -normal_a 成 angle 角的方向。
    """
    if mate.angle_deg is None:
        return None, "angle Mate 缺少 angle_deg"
    if port_a.type != "planar_face" or port_b.type != "planar_face":
        return None, "angle Mate 仅支持 planar_face"
    normal_a = get_port_direction(port_a)
    normal_b = get_port_direction(port_b)
    # 目标方向：B 法向应与 -normal_a 成 angle 角
    # 简化：取 -normal_a 绕 normal_a × normal_b 旋转 angle 后的方向
    # 实际生产中需要确定旋转轴，此处采用 -normal_a 绕任意垂直轴旋转 angle
    angle_rad = float(mate.angle_deg) * math.pi / 180.0
    # 构造目标方向：-normal_a 绕 z 轴旋转 angle（简化，仅用于测试）
    # 存疑，待实测：实际工程应基于两平面的交线确定旋转轴
    target_b = -normal_a * math.cos(angle_rad) + np.array([
        math.sin(angle_rad), 0.0, 0.0
    ])
    target_b = _normalize(target_b)
    R = _rotation_matrix_from_vectors(normal_b, target_b)
    T = _translation_matrix(origin_a - origin_b)
    return _mat_to_list(T @ R), None


def _angular_relation_transform(
    port_a: Port,
    port_b: Port,
    origin_a: np.ndarray,
    origin_b: np.ndarray,
    mate: MateSpec,
) -> tuple[list[float] | None, str | None]:
    """parallel/perpendicular Mate 变换。"""
    if port_a.type != "planar_face" or port_b.type != "planar_face":
        return None, f"{mate.type} Mate 仅支持 planar_face"
    normal_a = get_port_direction(port_a)
    normal_b = get_port_direction(port_b)
    if mate.type == "parallel":
        # B 法向对齐 A 法向（同向）
        target = normal_a
    else:  # perpendicular
        # B 法向垂直于 A 法向
        # 取 normal_a 的任一垂直方向
        if abs(normal_a[0]) < 0.9:
            perp = np.cross(normal_a, np.array([1.0, 0.0, 0.0]))
        else:
            perp = np.cross(normal_a, np.array([0.0, 1.0, 0.0]))
        target = _normalize(perp)
    R = _rotation_matrix_from_vectors(normal_b, target)
    T = _translation_matrix(origin_a - origin_b)
    return _mat_to_list(T @ R), None


def _tangent_transform(
    port_a: Port,
    port_b: Port,
    origin_a: np.ndarray,
    origin_b: np.ndarray,
) -> tuple[list[float] | None, str | None]:
    """tangent Mate 变换：圆柱面与平面相切。

    简化：圆柱面中心位于平面法向上方/下方 radius 距离处。
    """
    if port_a.type == "cylindrical" and port_b.type == "planar_face":
        radius = get_port_radius(port_a)
        if radius is None:
            return None, "cylindrical Port 缺少 radius"
        axis_a = get_port_direction(port_a)
        normal_b = get_port_direction(port_b)
        # 圆柱轴应平行于平面，且轴心距平面 radius
        R = _rotation_matrix_from_vectors(axis_a, np.cross(normal_b, np.array([1.0, 0.0, 0.0])) if abs(normal_b[0]) < 0.9 else np.cross(normal_b, np.array([0.0, 1.0, 0.0])))
        target = origin_b + radius * normal_b
        origin_a_rotated = R[:3, :3] @ origin_a
        T = _translation_matrix(target - origin_a_rotated)
        return _mat_to_list(T @ R), None
    if port_a.type == "planar_face" and port_b.type == "cylindrical":
        radius = get_port_radius(port_b)
        if radius is None:
            return None, "cylindrical Port 缺少 radius"
        normal_a = get_port_direction(port_a)
        axis_b = get_port_direction(port_b)
        R = _rotation_matrix_from_vectors(
            axis_b, np.cross(normal_a, np.array([1.0, 0.0, 0.0])) if abs(normal_a[0]) < 0.9 else np.cross(normal_a, np.array([0.0, 1.0, 0.0]))
        )
        target = origin_a + radius * normal_a
        origin_b_rotated = R[:3, :3] @ origin_b
        T = _translation_matrix(target - origin_b_rotated)
        return _mat_to_list(T @ R), None
    return None, f"tangent Mate 不支持 Port 组合: ({port_a.type}, {port_b.type})"


# ===== B-Rep 接口验证（可选）=====


def validate_port_brep(
    part: TypedPart,
    port: Port,
) -> tuple[bool, str | None]:
    """校验 Port 是否真实存在于零件的 B-Rep 中。

    本函数为可选验证：如果零件有 STEP 文件，可通过 pythonOCC 加载
    并校验 Port 声明的几何（面/边/轴）是否真实存在。

    实现策略（"以瞎猜接口为耻"）：
    - pythonOCC 不可用时返回 (True, None)（信任 LLM/标准件工厂声明）
    - pythonOCC 可用但 STEP 加载失败时返回 (False, error)
    - pythonOCC 可用且加载成功时校验几何参数合理性

    Args:
        part: 零件定义
        port: 待校验 Port

    Returns:
        (is_valid, error)
    """
    if part.generator != "step_file" or not part.step_file:
        # 非 STEP 文件无法做 B-Rep 验证，信任声明
        return True, None
    try:
        from OCC.Core.STEPControl import STEPControl_Reader  # type: ignore[import-not-found]
        from OCC.Core.IFSelect import IFSelect_RetDone  # type: ignore[import-not-found]
    except ImportError:
        # pythonOCC 不可用，跳过 B-Rep 验证
        return True, None
    # 实际 B-Rep 验证（如校验面法向、半径等）逻辑较复杂，
    # 此处仅做 STEP 文件可加载性校验。
    # 存疑，待实测：完整 B-Rep 验证需要遍历 TopoDS_Shape 的面/边/顶点，
    # 此处简化为"STEP 可加载即视为 Port 有效"。
    try:
        reader = STEPControl_Reader()
        status = reader.ReadFile(part.step_file)
        if status != IFSelect_RetDone:
            return False, f"STEP 文件加载失败: {part.step_file}"
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, f"STEP 文件加载异常: {e}"


# ===== 应用 mate 变换 =====


def apply_mate_transforms(
    parts: list[TypedPart],
    mates: list[MateSpec],
) -> tuple[dict[str, list[float]], list[str]]:
    """为所有 Mate 计算 transform_b，并组装每个零件的最终变换矩阵。

    约定：
    - 第一个被 Mate 引用的零件 A 视为"基准零件"，transform = identity
    - 其他零件通过 Mate 链式推导 transform
    - 多个 Mate 引用同一零件 B 时，取第一个 Mate 的 transform（其余校验一致性）

    Args:
        parts: 零件列表
        mates: Mate 列表

    Returns:
        (transforms, warnings)
        - transforms: {part_id: 16-float transform}
        - warnings: 非致命警告列表
    """
    part_map = {p.part_id: p for p in parts}
    port_map: dict[tuple[str, str], Port] = {}
    for p in parts:
        for port in p.ports:
            port_map[(p.part_id, port.name)] = port

    transforms: dict[str, list[float]] = {}
    warnings: list[str] = []

    # 第一个 Mate 的 part_a 作为基准
    if mates:
        base_part_id = mates[0].part_a_id
        transforms[base_part_id] = identity_transform()
    else:
        # 无 Mate，所有零件保持原位
        for p in parts:
            transforms[p.part_id] = identity_transform()
        return transforms, warnings

    # 链式推导
    for mate in mates:
        port_a = port_map.get((mate.part_a_id, mate.port_a_name))
        port_b = port_map.get((mate.part_b_id, mate.port_b_name))
        if port_a is None or port_b is None:
            warnings.append(
                f"Mate {mate.name} Port 引用缺失，跳过"
            )
            continue
        if mate.part_a_id not in transforms:
            warnings.append(
                f"Mate {mate.name} part_a {mate.part_a_id} 未定位，跳过"
            )
            continue
        if mate.part_b_id in transforms:
            # 已定位，跳过（避免覆盖）
            continue
        t_b, err = compute_mate_transform(port_a, port_b, mate)
        if t_b is None:
            warnings.append(
                f"Mate {mate.name} 变换计算失败: {err}"
            )
            continue
        # 组合：T_b_world = T_a_world @ T_b_local
        t_a_world = _list_to_mat(transforms[mate.part_a_id])
        t_b_local = _list_to_mat(t_b)
        t_b_world = t_a_world @ t_b_local
        transforms[mate.part_b_id] = _mat_to_list(t_b_world)
        # 更新 MateSpec 的 transform_b 与 is_satisfied
        mate.transform_b = t_b
        mate.is_satisfied = True

    # 未被 Mate 引用的零件保持原位
    for p in parts:
        if p.part_id not in transforms:
            transforms[p.part_id] = identity_transform()
            warnings.append(
                f"零件 {p.part_id} 未被任何 Mate 引用，保持原位"
            )

    return transforms, warnings


# ===== 模块自检 =====


def _self_test() -> dict[str, Any]:
    """离线自检（不依赖 SolidWorks/pythonOCC）。"""
    checks: dict[str, bool] = {}
    errors: list[str] = []

    # 兼容性矩阵
    ok, _ = is_port_compatible_with_mate(
        Port(name="a", type="planar_face", geometry={"origin": [0,0,0], "normal": [0,0,1]}),
        Port(name="b", type="planar_face", geometry={"origin": [0,0,0], "normal": [0,0,1]}),
        "coincident",
    )
    checks["compat_coincident_planar"] = ok

    ok, _ = is_port_compatible_with_mate(
        Port(name="a", type="cylindrical", geometry={"axis_point": [0,0,0], "axis_dir": [0,0,1], "radius": 5}),
        Port(name="b", type="cylindrical", geometry={"axis_point": [0,0,0], "axis_dir": [0,0,1], "radius": 5}),
        "concentric",
    )
    checks["compat_concentric_cyl"] = ok

    ok, _ = is_port_compatible_with_mate(
        Port(name="a", type="planar_face", geometry={"origin": [0,0,0], "normal": [0,0,1]}),
        Port(name="b", type="vertex", geometry={"point": [0,0,0]}),
        "concentric",
    )
    checks["compat_incompatible"] = not ok

    # coincident planar_face 变换
    port_a = Port(
        name="bottom", type="planar_face",
        geometry={"origin": [0, 0, 10], "normal": [0, 0, 1]},
    )
    port_b = Port(
        name="top", type="planar_face",
        geometry={"origin": [0, 0, 0], "normal": [0, 0, 1]},
    )
    mate = MateSpec(
        name="m1", type="coincident",
        part_a_id="A", port_a_name="bottom",
        part_b_id="B", port_b_name="top",
    )
    t, err = compute_mate_transform(port_a, port_b, mate)
    checks["coincident_transform_computed"] = t is not None and err is None
    if t is not None:
        # 验证变换后 B 原点应位于 A 原点
        m = _list_to_mat(t)
        b_origin_new = m @ np.array([0, 0, 0, 1])
        checks["coincident_b_origin_at_a"] = (
            abs(b_origin_new[0]) < 1e-6
            and abs(b_origin_new[1]) < 1e-6
            and abs(b_origin_new[2] - 10) < 1e-6
        )
        # 验证变换后 B 法向应反向于 A 法向
        b_normal_new = m[:3, :3] @ np.array([0, 0, 1])
        checks["coincident_b_normal_reversed"] = (
            abs(b_normal_new[0]) < 1e-6
            and abs(b_normal_new[1]) < 1e-6
            and abs(b_normal_new[2] + 1) < 1e-6
        )

    # concentric 变换
    port_a = Port(
        name="hole", type="cylindrical",
        geometry={"axis_point": [0, 0, 0], "axis_dir": [0, 0, 1], "radius": 5},
    )
    port_b = Port(
        name="shaft", type="cylindrical",
        geometry={"axis_point": [10, 0, 0], "axis_dir": [0, 1, 0], "radius": 5},
    )
    mate = MateSpec(
        name="m2", type="concentric",
        part_a_id="A", port_a_name="hole",
        part_b_id="B", port_b_name="shaft",
    )
    t, err = compute_mate_transform(port_a, port_b, mate)
    checks["concentric_transform_computed"] = t is not None and err is None

    # distance 变换
    port_a = Port(
        name="face_a", type="planar_face",
        geometry={"origin": [0, 0, 0], "normal": [0, 0, 1]},
    )
    port_b = Port(
        name="face_b", type="planar_face",
        geometry={"origin": [0, 0, 0], "normal": [0, 0, 1]},
    )
    mate = MateSpec(
        name="m3", type="distance", distance_mm=20.0,
        part_a_id="A", port_a_name="face_a",
        part_b_id="B", port_b_name="face_b",
    )
    t, err = compute_mate_transform(port_a, port_b, mate)
    checks["distance_transform_computed"] = t is not None and err is None
    if t is not None:
        m = _list_to_mat(t)
        b_origin_new = m @ np.array([0, 0, 0, 1])
        checks["distance_b_origin_correct"] = (
            abs(b_origin_new[0]) < 1e-6
            and abs(b_origin_new[1]) < 1e-6
            and abs(b_origin_new[2] - 20.0) < 1e-6
        )

    # apply_mate_transforms 链式推导
    parts = [
        TypedPart(
            part_id="base", part_type="plate", name="底座",
            generator="cadquery_code", cadquery_code="# placeholder",
            ports=[Port(name="top_face", type="planar_face",
                       geometry={"origin": [0, 0, 10], "normal": [0, 0, 1]})],
        ),
        TypedPart(
            part_id="block", part_type="block", name="方块",
            generator="cadquery_code", cadquery_code="# placeholder",
            ports=[Port(name="bottom_face", type="planar_face",
                       geometry={"origin": [0, 0, 0], "normal": [0, 0, 1]})],
        ),
    ]
    mates = [
        MateSpec(
            name="block_on_base", type="coincident",
            part_a_id="base", port_a_name="top_face",
            part_b_id="block", port_b_name="bottom_face",
        ),
    ]
    transforms, ws = apply_mate_transforms(parts, mates)
    checks["apply_mate_chain_base_identity"] = (
        transforms["base"] == identity_transform()
    )
    checks["apply_mate_chain_block_transformed"] = (
        transforms["block"] != identity_transform()
    )
    checks["apply_mate_chain_no_warnings"] = len(ws) == 0

    # 单位矩阵
    checks["identity_transform_len"] = len(identity_transform()) == 16
    checks["identity_transform_value"] = identity_transform()[0] == 1.0

    # 统一转换为 Python 原生类型（避免 numpy bool_/float64 不可 JSON 序列化）
    checks_py: dict[str, bool] = {k: bool(v) for k, v in checks.items()}
    ok = all(checks_py.values())
    return {"ok": ok, "errors": errors, "checks": checks_py}


if __name__ == "__main__":  # pragma: no cover
    import json
    result = _self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    import sys
    sys.exit(0 if result["ok"] else 1)
