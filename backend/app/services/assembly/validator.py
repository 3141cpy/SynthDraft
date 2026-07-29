"""装配验证管线（Task 10.4）。

实现 AssemCAD 范式的 4 类确定性验证：
1. interface_match：Port-Mate 类型兼容性
2. interference：零件间几何干涉（基于包围盒）
3. connectivity：装配关系图连通性（并查集）
4. degree_of_freedom：自由度约束（每零件至少 1 个 Mate）

外加 axiom_results：用户自定义公理验证。

设计原则：
- 不依赖 pythonOCC（纯 Python + numpy），可跨平台运行
- 干涉检查使用 AABB（轴对齐包围盒）保守估计
- 连通性使用并查集（Union-Find）
- 自由度简化模型：每个 Mate 减少若干自由度（coincident 3 / concentric 2 / distance 1 / lock 6）

参考：
- AssemCAD: https://arxiv.org/html/2607.05123v1
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from app.logging import get_logger
from app.schemas.assembly import (
    AssemblySpec,
    AssemblyValidationReport,
    EngineeringAxiom,
    MateSpec,
    Port,
    TypedPart,
)
from app.services.assembly.mate_library import (
    apply_mate_transforms,
    is_port_compatible_with_mate,
    _list_to_mat,
)

log = get_logger(__name__)


# Mate 减少的自由度数（简化模型）
# 6 自由度：3 平移 + 3 旋转
_MATE_DOF_REMOVED: dict[str, int] = {
    "coincident": 3,    # 面贴合：去除 1 平移 + 2 旋转
    "concentric": 4,    # 同轴：去除 2 平移 + 2 旋转（保留沿轴平移 + 绕轴旋转）
    "parallel": 2,      # 面平行：去除 2 旋转
    "perpendicular": 2, # 面垂直：去除 2 旋转
    "tangent": 1,       # 相切：去除 1 平移
    "distance": 1,      # 距离：去除 1 平移
    "angle": 1,         # 角度：去除 1 旋转
    "lock": 6,          # 锁定：完全约束
    "unknown": 0,
}


# ===== 主入口 =====


def validate_assembly(spec: AssemblySpec) -> AssemblyValidationReport:
    """执行装配验证管线（4 类 + 自定义公理）。

    Args:
        spec: 装配规范

    Returns:
        AssemblyValidationReport
    """
    t_start = time.perf_counter()
    log.info(
        "assembly.validate.start",
        name=spec.name,
        parts=len(spec.parts),
        mates=len(spec.mates),
        axioms=len(spec.axioms),
    )

    report = AssemblyValidationReport(assembly_name=spec.name)

    # 1. 接口有效性（Port-Mate 兼容性）
    report.interface_match = _validate_interface_match(spec)
    interface_pass = all(
        item.get("is_compatible", False) for item in report.interface_match
    )

    # 2. 干涉一致性（基于 AABB）
    report.interference = _validate_interference(spec)
    interference_pass = all(
        not item.get("interferes", False) for item in report.interference
    )

    # 3. 图连通性（并查集）
    report.connectivity = _validate_connectivity(spec)
    connectivity_pass = report.connectivity.get("is_connected", False)

    # 4. 自由度约束
    report.degree_of_freedom = _validate_dof(spec)
    dof_pass = all(
        item.get("is_constrained", False) for item in report.degree_of_freedom
    )

    # 5. 自定义公理
    report.axiom_results = _validate_axioms(spec)
    axioms_pass = all(
        item.get("is_satisfied", False) for item in report.axiom_results
    )

    # 统计
    report.passed_count = sum([
        int(interface_pass), int(interference_pass),
        int(connectivity_pass), int(dof_pass), int(axioms_pass),
    ])
    report.failed_count = 5 - report.passed_count
    report.warning_count = len(spec.warnings)

    report.is_valid = (
        interface_pass and interference_pass
        and connectivity_pass and dof_pass and axioms_pass
    )
    report.elapsed_ms = int((time.perf_counter() - t_start) * 1000)

    log.info(
        "assembly.validate.done",
        name=spec.name,
        is_valid=report.is_valid,
        passed=report.passed_count,
        failed=report.failed_count,
        elapsed_ms=report.elapsed_ms,
    )
    return report


# ===== 验证 1：接口有效性 =====


def _validate_interface_match(spec: AssemblySpec) -> list[dict[str, Any]]:
    """校验所有 Mate 的 Port 类型兼容性。"""
    port_map: dict[tuple[str, str], Port] = {}
    for p in spec.parts:
        for port in p.ports:
            port_map[(p.part_id, port.name)] = port

    results: list[dict[str, Any]] = []
    for mate in spec.mates:
        port_a = port_map.get((mate.part_a_id, mate.port_a_name))
        port_b = port_map.get((mate.part_b_id, mate.port_b_name))
        if port_a is None or port_b is None:
            results.append({
                "mate_name": mate.name,
                "is_compatible": False,
                "reason": "Port 引用缺失",
            })
            continue
        ok, reason = is_port_compatible_with_mate(port_a, port_b, mate.type)
        results.append({
            "mate_name": mate.name,
            "mate_type": mate.type,
            "port_a": f"{mate.part_a_id}.{mate.port_a_name} ({port_a.type})",
            "port_b": f"{mate.part_b_id}.{mate.port_b_name} ({port_b.type})",
            "is_compatible": ok,
            "reason": reason,
        })
    return results


# ===== 验证 2：干涉一致性（基于 AABB）=====


def _validate_interference(spec: AssemblySpec) -> list[dict[str, Any]]:
    """基于 AABB 包围盒的零件间干涉检查。

    策略：
    1. 为每个零件计算 AABB（来自其几何信息或默认包围盒）
    2. 应用 mate 变换后的世界 AABB
    3. 检查所有零件对的 AABB 相交

    注意：AABB 是保守估计，实际 B-Rep 干涉需要 pythonOCC。
    本实现为离线快速检查，存在误报（实际不干涉但 AABB 相交）。

    已知误报场景（特例豁免）：
    - ``concentric`` mate 的孔-轴配合（如 bolt 同轴穿过 flange 中心孔）：
      AABB 必相交（轴 AABB 在孔零件 AABB 内），但实际 B-Rep 不干涉
      （孔径 > 轴径）。当 ``_has_concentric_axis_hole_exception`` 判定成立时，
      标注 ``interferes=False`` 并附 ``note`` 字段，需 pythonOCC 做精确判定。
    """
    transforms, _ = apply_mate_transforms(spec.parts, spec.mates)
    # 计算每个零件的世界 AABB
    aabbs: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for part in spec.parts:
        local_aabb = _estimate_part_aabb(part)
        t_world = _list_to_mat(transforms.get(part.part_id, _identity_16()))
        world_aabb = _transform_aabb(local_aabb, t_world)
        aabbs[part.part_id] = world_aabb

    results: list[dict[str, Any]] = []
    parts = spec.parts
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            pa, pb = parts[i], parts[j]
            aabb_a, aabb_b = aabbs[pa.part_id], aabbs[pb.part_id]
            interferes = _aabb_intersects(aabb_a, aabb_b)
            note: str | None = None
            # concentric mate 孔-轴特例豁免：AABB 误报，实际不干涉
            if interferes and _has_concentric_axis_hole_exception(spec, pa, pb):
                interferes = False
                note = "concentric mate 孔-轴特例豁免（AABB 误报，需 B-Rep 精确判定）"
            item: dict[str, Any] = {
                "part_a": pa.part_id,
                "part_b": pb.part_id,
                "interferes": interferes,
                "aabb_a_min": [float(x) for x in aabb_a[0]],
                "aabb_a_max": [float(x) for x in aabb_a[1]],
                "aabb_b_min": [float(x) for x in aabb_b[0]],
                "aabb_b_max": [float(x) for x in aabb_b[1]],
            }
            if note is not None:
                item["note"] = note
            results.append(item)
    return results


def _has_concentric_axis_hole_exception(
    spec: AssemblySpec,
    part_a: TypedPart,
    part_b: TypedPart,
) -> bool:
    """判断两个零件间是否存在 concentric mate 的孔-轴豁免。

    当 ``bolt``/``shaft`` 同轴穿过 ``flange``/``bearing`` 的孔，且孔径 > 轴径时，
    AABB 必相交但 B-Rep 实际不干涉，应跳过 AABB 干涉判定。

    判定条件：
    1. 两零件间存在 ``concentric`` mate
    2. 一方为轴类零件（``bolt`` / ``shaft``），另一方为孔类零件
       （``flange`` / ``bearing``）
    3. 孔径 > 轴径（确保物理上不干涉）

    注意：此为对 AABB 保守估计的已知误报的特例豁免，
    精确判定应使用 pythonOCC B-Rep 干涉检查。
    """
    # 查找两个零件间的 concentric mate
    has_concentric = any(
        m.type == "concentric"
        and (
            (m.part_a_id == part_a.part_id and m.part_b_id == part_b.part_id)
            or (m.part_a_id == part_b.part_id and m.part_b_id == part_a.part_id)
        )
        for m in spec.mates
    )
    if not has_concentric:
        return False

    def _axis_diameter(p: TypedPart) -> float | None:
        """轴类零件的轴径（mm）。"""
        if p.part_type == "bolt":
            # bolt.parameters["m"] 为螺纹公称直径（轴径）
            return float(p.parameters.get("m", 0.0))  # type: ignore[arg-type]
        if p.part_type == "shaft":
            return float(p.parameters.get("diameter", 0.0))  # type: ignore[arg-type]
        return None

    def _hole_diameter(p: TypedPart) -> float | None:
        """孔类零件的孔径（mm）。"""
        if p.part_type in ("flange", "bearing"):
            # flange/bearing 的 inner_diameter 即为孔径
            return float(p.parameters.get("inner_diameter", 0.0))  # type: ignore[arg-type]
        return None

    a_axis = _axis_diameter(part_a)
    a_hole = _hole_diameter(part_a)
    b_axis = _axis_diameter(part_b)
    b_hole = _hole_diameter(part_b)

    # 一方为轴，另一方为孔，且孔径严格 > 轴径
    if a_axis is not None and b_hole is not None and b_hole > a_axis > 0.0:
        return True
    if b_axis is not None and a_hole is not None and a_hole > b_axis > 0.0:
        return True
    return False


def _identity_16() -> list[float]:
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _estimate_part_aabb(part: TypedPart) -> tuple[np.ndarray, np.ndarray]:
    """根据零件参数估计局部 AABB（min, max）。"""
    # 根据 part_type 给出粗略包围盒
    if part.part_type == "bolt":
        m = float(part.parameters.get("m", 8.0))  # type: ignore[arg-type]
        length = float(part.parameters.get("length", 30.0))  # type: ignore[arg-type]
        head_d = float(part.parameters.get("head_diameter", 1.5 * m))  # type: ignore[arg-type]
        r = head_d / 2
        return np.array([-r, -r, -length]), np.array([r, r, 0.6 * m])
    if part.part_type == "bearing":
        outer_d = float(part.parameters.get("outer_diameter", 28.0))  # type: ignore[arg-type]
        width = float(part.parameters.get("width", 8.0))  # type: ignore[arg-type]
        r = outer_d / 2
        return np.array([-r, -r, 0.0]), np.array([r, r, width])
    if part.part_type == "shaft":
        diameter = float(part.parameters.get("diameter", 20.0))  # type: ignore[arg-type]
        length = float(part.parameters.get("length", 80.0))  # type: ignore[arg-type]
        r = diameter / 2
        return np.array([-r, -r, 0.0]), np.array([r, r, length])
    if part.part_type == "flange":
        outer_d = float(part.parameters.get("outer_diameter", 100.0))  # type: ignore[arg-type]
        thickness = float(part.parameters.get("thickness", 10.0))  # type: ignore[arg-type]
        r = outer_d / 2
        return np.array([-r, -r, 0.0]), np.array([r, r, thickness])
    if part.part_type == "key":
        length = float(part.parameters.get("length", 20.0))  # type: ignore[arg-type]
        width = float(part.parameters.get("width", 6.0))  # type: ignore[arg-type]
        height = float(part.parameters.get("height", 6.0))  # type: ignore[arg-type]
        return np.array([-length / 2, -width / 2, -height / 2]), \
               np.array([length / 2, width / 2, height / 2])
    if part.part_type == "gear":
        outer_d = float(part.parameters.get("module", 2.0))  # type: ignore[arg-type]
        teeth = int(part.parameters.get("teeth", 20))  # type: ignore[arg-type]
        thickness = float(part.parameters.get("thickness", 15.0))  # type: ignore[arg-type]
        r = (outer_d * teeth + 2 * outer_d) / 2
        return np.array([-r, -r, 0.0]), np.array([r, r, thickness])
    # 默认：50×50×50 立方体
    return np.array([-25.0, -25.0, -25.0]), np.array([25.0, 25.0, 25.0])


def _transform_aabb(
    aabb: tuple[np.ndarray, np.ndarray],
    transform: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """应用 4×4 变换矩阵到 AABB，返回新的 AABB（保守放大）。"""
    corners = np.array([
        [aabb[0][0], aabb[0][1], aabb[0][2], 1.0],
        [aabb[0][0], aabb[0][1], aabb[1][2], 1.0],
        [aabb[0][0], aabb[1][1], aabb[0][2], 1.0],
        [aabb[0][0], aabb[1][1], aabb[1][2], 1.0],
        [aabb[1][0], aabb[0][1], aabb[0][2], 1.0],
        [aabb[1][0], aabb[0][1], aabb[1][2], 1.0],
        [aabb[1][0], aabb[1][1], aabb[0][2], 1.0],
        [aabb[1][0], aabb[1][1], aabb[1][2], 1.0],
    ])
    transformed = (transform @ corners.T).T
    new_min = transformed[:, :3].min(axis=0)
    new_max = transformed[:, :3].max(axis=0)
    return new_min, new_max


def _aabb_intersects(
    a: tuple[np.ndarray, np.ndarray],
    b: tuple[np.ndarray, np.ndarray],
) -> bool:
    """AABB 相交判定（边界相切不算干涉）。

    装配体中两个零件贴合（如法兰盘面贴合）时，AABB 边界会精确相切，
    此时应判定为"不干涉"（仅接触，无体积重叠）。
    严格内部相交才视为干涉：a_max > b_min 且 b_max > a_min。
    """
    for i in range(3):
        # 不相交（含相切）：a_max <= b_min 或 b_max <= a_min
        if a[1][i] <= b[0][i] or b[1][i] <= a[0][i]:
            return False
    return True


# ===== 验证 3：图连通性（并查集）=====


def _validate_connectivity(spec: AssemblySpec) -> dict[str, Any]:
    """并查集校验装配关系图连通性。"""
    if not spec.parts:
        return {"is_connected": True, "components": 0, "orphans": []}

    parent: dict[str, str] = {p.part_id: p.part_id for p in spec.parts}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for mate in spec.mates:
        if mate.part_a_id in parent and mate.part_b_id in parent:
            union(mate.part_a_id, mate.part_b_id)

    roots: dict[str, list[str]] = {}
    for pid in parent:
        r = find(pid)
        roots.setdefault(r, []).append(pid)

    orphans = [
        pid for pid, p in zip(parent.keys(), spec.parts)
        if find(pid) == pid and not any(
            m.part_a_id == pid or m.part_b_id == pid for m in spec.mates
        )
    ]

    return {
        "is_connected": len(roots) == 1,
        "components": len(roots),
        "orphans": orphans,
        "component_groups": list(roots.values()),
    }


# ===== 验证 4：自由度约束 =====


def _validate_dof(spec: AssemblySpec) -> list[dict[str, Any]]:
    """自由度约束验证（每零件至少 1 个 Mate，理想情况完全约束）。"""
    results: list[dict[str, Any]] = []
    for part in spec.parts:
        mate_count = sum(
            1 for m in spec.mates
            if m.part_a_id == part.part_id or m.part_b_id == part.part_id
        )
        dof_removed = 0
        for m in spec.mates:
            if m.part_a_id == part.part_id or m.part_b_id == part.part_id:
                dof_removed += _MATE_DOF_REMOVED.get(m.type, 0)
        # 6 自由度 - 已约束 = 剩余自由度
        remaining_dof = max(0, 6 - dof_removed)
        # 简化：mate_count >= 1 视为"已约束"（实际生产需要更精细）
        is_constrained = mate_count >= 1
        results.append({
            "part_id": part.part_id,
            "mate_count": mate_count,
            "dof_removed": dof_removed,
            "remaining_dof": remaining_dof,
            "is_constrained": is_constrained,
            "note": "完全约束" if remaining_dof == 0 else (
                "部分约束" if is_constrained else "未约束"
            ),
        })
    return results


# ===== 验证 5：自定义公理 =====


def _validate_axioms(spec: AssemblySpec) -> list[dict[str, Any]]:
    """校验用户自定义工程公理。"""
    results: list[dict[str, Any]] = []
    for axiom in spec.axioms:
        result = _validate_single_axiom(spec, axiom)
        results.append(result)
    return results


def _validate_single_axiom(
    spec: AssemblySpec,
    axiom: EngineeringAxiom,
) -> dict[str, Any]:
    """校验单条公理。"""
    category = axiom.category
    params = axiom.parameters

    if category == "interference":
        # 复用干涉检查结果
        pa = params.get("part_a_id")
        pb = params.get("part_b_id")
        for item in _validate_interference(spec):
            # 用集合比较，避免 (A,B) vs (B,A) 顺序敏感导致公理校验误报
            if {item["part_a"], item["part_b"]} == {pa, pb}:
                interferes = item["interferes"]
                return {
                    "axiom_name": axiom.name,
                    "category": category,
                    "is_satisfied": not interferes,
                    "evidence": f"零件 {pa} 与 {pb} "
                                f"{'干涉' if interferes else '不干涉'}",
                }
        return {
            "axiom_name": axiom.name,
            "category": category,
            "is_satisfied": False,
            "evidence": f"未找到零件对 {pa}/{pb}",
        }

    if category == "connectivity":
        conn = _validate_connectivity(spec)
        return {
            "axiom_name": axiom.name,
            "category": category,
            "is_satisfied": conn["is_connected"],
            "evidence": f"连通分量数 {conn['components']}",
        }

    if category == "degree_of_freedom":
        pid = params.get("part_id")
        expected = params.get("expected_dof", 0)
        for item in _validate_dof(spec):
            if item["part_id"] == pid:
                actual = item["remaining_dof"]
                return {
                    "axiom_name": axiom.name,
                    "category": category,
                    "is_satisfied": actual <= expected,
                    "evidence": f"零件 {pid} 剩余自由度 {actual}（期望 ≤ {expected}）",
                }
        return {
            "axiom_name": axiom.name,
            "category": category,
            "is_satisfied": False,
            "evidence": f"未找到零件 {pid}",
        }

    if category == "interface_match":
        mate_name = params.get("mate_name")
        for item in _validate_interface_match(spec):
            if item["mate_name"] == mate_name:
                ok = item["is_compatible"]
                return {
                    "axiom_name": axiom.name,
                    "category": category,
                    "is_satisfied": ok,
                    "evidence": item.get("reason", "") or "接口匹配",
                }
        return {
            "axiom_name": axiom.name,
            "category": category,
            "is_satisfied": False,
            "evidence": f"未找到 Mate {mate_name}",
        }

    if category == "bom_complete":
        # 每个 part 必须有 part_number 与 material
        missing = [
            p.part_id for p in spec.parts
            if not p.part_number or not p.material
        ]
        return {
            "axiom_name": axiom.name,
            "category": category,
            "is_satisfied": len(missing) == 0,
            "evidence": f"缺失 BOM 信息的零件: {missing}" if missing else "全部零件 BOM 完整",
        }

    # custom 公理：直接返回 is_satisfied 字段（信任用户预设）
    return {
        "axiom_name": axiom.name,
        "category": category,
        "is_satisfied": axiom.is_satisfied,
        "evidence": axiom.description,
    }


# ===== 模块自检 =====


def _self_test() -> dict[str, Any]:
    """离线自检：4 类验证 + 自定义公理。"""
    from app.services.assembly.standard_parts import create_part

    checks: dict[str, bool] = {}

    # 构造一个有效装配体：底座 + 法兰盘（coincident）
    parts = [
        create_part("flange_plate", "base", {
            "outer_diameter": 100.0, "inner_diameter": 50.0, "thickness": 10.0,
        }),
        create_part("flange_plate", "top", {
            "outer_diameter": 100.0, "inner_diameter": 50.0, "thickness": 10.0,
        }),
    ]
    mates = [
        MateSpec(
            name="top_on_base", type="coincident",
            part_a_id="base", port_a_name="flange_face_b",
            part_b_id="top", port_b_name="flange_face_a",
        ),
    ]
    spec = AssemblySpec(
        name="测试装配体",
        parts=parts,
        mates=mates,
        axioms=[
            EngineeringAxiom(
                name="conn", category="connectivity",
                description="装配体应连通",
            ),
            EngineeringAxiom(
                name="bom", category="bom_complete",
                description="BOM 完整",
            ),
        ],
    )

    report = validate_assembly(spec)
    checks["valid_assembly_is_valid"] = report.is_valid
    checks["valid_interface_pass"] = all(
        item["is_compatible"] for item in report.interface_match
    )
    checks["valid_dof_pass"] = all(
        item["is_constrained"] for item in report.degree_of_freedom
    )
    checks["valid_connectivity_pass"] = report.connectivity["is_connected"]
    checks["valid_axioms_pass"] = all(
        item["is_satisfied"] for item in report.axiom_results
    )
    checks["valid_passed_count_5"] = report.passed_count == 5
    checks["valid_failed_count_0"] = report.failed_count == 0
    checks["valid_elapsed_ms_positive"] = report.elapsed_ms >= 0

    # 构造无效装配体：不兼容 Mate
    from app.schemas.assembly import Port
    parts_bad = [
        TypedPart(
            part_id="p1", part_type="plate", name="p1",
            generator="cadquery_code", cadquery_code="# x",
            ports=[Port(name="face", type="planar_face",
                       geometry={"origin": [0, 0, 0], "normal": [0, 0, 1]})],
        ),
        TypedPart(
            part_id="p2", part_type="plate", name="p2",
            generator="cadquery_code", cadquery_code="# x",
            ports=[Port(name="axis", type="axis",
                       geometry={"point": [0, 0, 0], "direction": [0, 0, 1]})],
        ),
    ]
    mates_bad = [
        MateSpec(
            name="bad", type="concentric",
            part_a_id="p1", port_a_name="face",
            part_b_id="p2", port_b_name="axis",
        ),
    ]
    spec_bad = AssemblySpec(name="无效装配体", parts=parts_bad, mates=mates_bad)
    report_bad = validate_assembly(spec_bad)
    checks["invalid_interface_fail"] = not all(
        item["is_compatible"] for item in report_bad.interface_match
    )
    checks["invalid_is_not_valid"] = not report_bad.is_valid

    # 孤儿零件测试
    parts_orphan = [
        create_part("flange_plate", "p1", {"outer_diameter": 100.0, "inner_diameter": 50.0, "thickness": 10.0}),
        create_part("flange_plate", "p2", {"outer_diameter": 100.0, "inner_diameter": 50.0, "thickness": 10.0}),
        create_part("flange_plate", "p3", {"outer_diameter": 100.0, "inner_diameter": 50.0, "thickness": 10.0}),
    ]
    mates_orphan = [
        MateSpec(
            name="m12", type="coincident",
            part_a_id="p1", port_a_name="flange_face_b",
            part_b_id="p2", port_b_name="flange_face_a",
        ),
    ]
    spec_orphan = AssemblySpec(name="孤儿测试", parts=parts_orphan, mates=mates_orphan)
    report_orphan = validate_assembly(spec_orphan)
    checks["orphan_connectivity_fail"] = not report_orphan.connectivity["is_connected"]
    checks["orphan_has_orphan_p3"] = "p3" in report_orphan.connectivity["orphans"]
    checks["orphan_dof_p3_unconstrained"] = any(
        item["part_id"] == "p3" and not item["is_constrained"]
        for item in report_orphan.degree_of_freedom
    )

    # 空装配体边界
    spec_empty = AssemblySpec(name="空", parts=[], mates=[])
    report_empty = validate_assembly(spec_empty)
    checks["empty_is_valid"] = report_empty.is_valid

    ok = all(checks.values())
    return {"ok": ok, "checks": checks}


if __name__ == "__main__":  # pragma: no cover
    import json
    result = _self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    import sys
    sys.exit(0 if result["ok"] else 1)
