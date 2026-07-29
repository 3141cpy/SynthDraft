"""标准件参数化组件工厂（Task 10.3）。

为常见标准件提供参数化生成能力，输出 CadQuery 代码 + Port 声明：
- 螺栓（ISO 4762 内六角 / ISO 4014 六角头）
- 轴承（深沟球轴承 6000 系列）
- 齿轮（直齿圆柱齿轮，简化参数化）
- 轴（阶梯轴）
- 法兰盘
- 平键

每个工厂返回 TypedPart，包含：
- cadquery_code：可在沙箱执行的 CadQuery 代码（生成 STEP）
- ports：典型 Port 声明（轴向/径向/端面）
- bom 信息（件号/材料/质量）

设计原则：
- 参数来自 GB/T / ISO 标准，工厂内硬编码默认值
- 生成的 CadQuery 代码遵循 sandbox.py 执行规范（变量 `result` 为 cq.Workplane）
- Port 坐标系：零件局部坐标系，z 轴为轴向
- 单位：mm

参考：
- ISO 4762: 内六角圆柱头螺栓
- GB/T 276: 深沟球轴承
- GB/T 1096: 普通平键
- CadQuery 文档: https://cadquery.readthedocs.io/
"""

from __future__ import annotations

from typing import Any

from app.logging import get_logger
from app.schemas.assembly import Port, TypedPart

log = get_logger(__name__)


# ===== 工厂注册表 =====

FACTORIES: dict[str, Any] = {}


def register(name: str) -> Any:
    """装饰器：注册标准件工厂。"""

    def decorator(fn: Any) -> Any:
        FACTORIES[name] = fn
        return fn

    return decorator


def get_factory(name: str) -> Any | None:
    """获取已注册的工厂函数。"""
    return FACTORIES.get(name)


def list_factories() -> list[str]:
    """列出所有已注册的工厂名。"""
    return sorted(FACTORIES.keys())


def create_part(
    standard_part_name: str,
    part_id: str,
    parameters: dict[str, float | str | bool],
    name: str | None = None,
    quantity: int = 1,
) -> TypedPart:
    """通用入口：根据标准件名调用对应工厂。

    Args:
        standard_part_name: 工厂名（如 "bolt_iso4762"）
        part_id: 实例唯一 ID
        parameters: 参数 dict（按工厂定义）
        name: 显示名（None 时由工厂生成）
        quantity: 数量

    Returns:
        TypedPart（generator=standard_part，含 cadquery_code 与 ports）

    Raises:
        ValueError: 工厂不存在或参数缺失
    """
    factory = get_factory(standard_part_name)
    if factory is None:
        raise ValueError(
            f"未知标准件工厂: {standard_part_name}（已注册: {list_factories()}）"
        )
    part = factory(part_id=part_id, parameters=parameters, name=name, quantity=quantity)
    return part


# ===== 内部辅助 =====


def _float_param(
    parameters: dict[str, float | str | bool],
    key: str,
    default: float,
) -> float:
    """提取 float 参数。"""
    v = parameters.get(key, default)
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError) as e:
        raise ValueError(f"参数 {key} 必须为数值，实际: {v!r}") from e


# ===== 工厂 1：内六角圆柱头螺栓（ISO 4762）=====


@register("bolt_iso4762")
def _bolt_iso4762(
    part_id: str,
    parameters: dict[str, float | str | bool],
    name: str | None,
    quantity: int,
) -> TypedPart:
    """ISO 4762 内六角圆柱头螺栓。

    参数：
    - m: 螺纹规格（M6/M8/M10/M12，默认 M8）
    - length: 螺杆长度（mm，默认 30）
    - head_diameter: 头部直径（mm，默认 1.5*m）
    - head_height: 头部高度（mm，默认 0.6*m）

    Port：
    - shaft_axis: 螺杆轴线（cylindrical）
    - head_bottom_face: 头部底面（planar_face）
    - tip_face: 螺杆尖端面（planar_face）
    """
    m = _float_param(parameters, "m", 8.0)
    length = _float_param(parameters, "length", 30.0)
    head_diameter = _float_param(parameters, "head_diameter", 1.5 * m)
    head_height = _float_param(parameters, "head_height", 0.6 * m)

    # 简化建模：圆柱头 + 圆柱螺杆（无螺纹，避免 CadQuery 螺纹开销）
    code = f"""
import cadquery as cq

m = {m}
length = {length}
head_diameter = {head_diameter}
head_height = {head_height}
shaft_diameter = m

# 头部
head = cq.Workplane("XY").circle(head_diameter / 2).extrude(head_height)
# 螺杆（沿 -z 方向）
shaft = cq.Workplane("XY").workplane(offset=-length).circle(
    shaft_diameter / 2
).extrude(length)
result = head.union(shaft)
"""

    ports = [
        Port(
            name="shaft_axis",
            type="cylindrical",
            geometry={
                "axis_point": [0.0, 0.0, -length / 2],
                "axis_dir": [0.0, 0.0, 1.0],
                "radius": m / 2,
            },
            sw_feature_name="shaft",
        ),
        Port(
            name="head_bottom_face",
            type="planar_face",
            geometry={
                "origin": [0.0, 0.0, 0.0],
                "normal": [0.0, 0.0, 1.0],
            },
            sw_feature_name="head_bottom",
        ),
        Port(
            name="tip_face",
            type="planar_face",
            geometry={
                "origin": [0.0, 0.0, -length],
                "normal": [0.0, 0.0, -1.0],
            },
            sw_feature_name="tip",
        ),
    ]

    display_name = name or f"M{int(m)}×{int(length)} 内六角螺栓"
    return TypedPart(
        part_id=part_id,
        part_type="bolt",
        name=display_name,
        parameters={
            "m": m, "length": length,
            "head_diameter": head_diameter, "head_height": head_height,
        },
        ports=ports,
        generator="standard_part",
        standard_part_name="bolt_iso4762",
        cadquery_code=code,
        part_number=f"ISO4762-M{int(m)}x{int(length)}",
        material="8.8 级碳钢",
        mass=0.05,
        quantity=quantity,
    )


# ===== 工厂 2：深沟球轴承（GB/T 276，6000 系列）=====


@register("bearing_6200")
def _bearing_6200(
    part_id: str,
    parameters: dict[str, float | str | bool],
    name: str | None,
    quantity: int,
) -> TypedPart:
    """深沟球轴承（GB/T 276，6000 系列）。

    参数：
    - outer_diameter: 外径 D（mm，默认 28，对应 6201）
    - inner_diameter: 内径 d（mm，默认 12）
    - width: 宽度 B（mm，默认 8）

    Port：
    - outer_ring_axis: 外圈外圆柱面（cylindrical）
    - inner_ring_axis: 内圈内圆柱面（cylindrical）
    - side_face_a: 侧面 A（planar_face）
    - side_face_b: 侧面 B（planar_face）
    """
    outer_d = _float_param(parameters, "outer_diameter", 28.0)
    inner_d = _float_param(parameters, "inner_diameter", 12.0)
    width = _float_param(parameters, "width", 8.0)

    # 简化建模：外圈环 - 内圈环（无滚珠，仅作几何占位）
    code = f"""
import cadquery as cq

outer_d = {outer_d}
inner_d = {inner_d}
width = {width}

# 外圈
outer = cq.Workplane("XY").circle(outer_d / 2).circle(inner_d / 2).extrude(width)
result = outer
"""

    ports = [
        Port(
            name="outer_ring_axis",
            type="cylindrical",
            geometry={
                "axis_point": [0.0, 0.0, width / 2],
                "axis_dir": [0.0, 0.0, 1.0],
                "radius": outer_d / 2,
            },
        ),
        Port(
            name="inner_ring_axis",
            type="cylindrical",
            geometry={
                "axis_point": [0.0, 0.0, width / 2],
                "axis_dir": [0.0, 0.0, 1.0],
                "radius": inner_d / 2,
            },
        ),
        Port(
            name="side_face_a",
            type="planar_face",
            geometry={
                "origin": [0.0, 0.0, 0.0],
                "normal": [0.0, 0.0, -1.0],
            },
        ),
        Port(
            name="side_face_b",
            type="planar_face",
            geometry={
                "origin": [0.0, 0.0, width],
                "normal": [0.0, 0.0, 1.0],
            },
        ),
    ]

    display_name = name or f"轴承 {int(inner_d)}×{int(outer_d)}×{int(width)}"
    return TypedPart(
        part_id=part_id,
        part_type="bearing",
        name=display_name,
        parameters={
            "outer_diameter": outer_d,
            "inner_diameter": inner_d,
            "width": width,
        },
        ports=ports,
        generator="standard_part",
        standard_part_name="bearing_6200",
        cadquery_code=code,
        part_number=f"6201-{int(inner_d)}x{int(outer_d)}",
        material="GCr15",
        mass=0.03,
        quantity=quantity,
    )


# ===== 工厂 3：阶梯轴 =====


@register("shaft_stepped")
def _shaft_stepped(
    part_id: str,
    parameters: dict[str, float | str | bool],
    name: str | None,
    quantity: int,
) -> TypedPart:
    """阶梯轴。

    参数：
    - length: 总长度（mm，默认 80）
    - diameter: 主轴径（mm，默认 20）
    - end_diameter: 端部轴径（mm，默认 15）
    - end_length: 端部长度（mm，默认 20）

    Port：
    - shaft_axis: 主轴轴线（cylindrical）
    - end_face_a: 端面 A（planar_face）
    - end_face_b: 端面 B（planar_face）
    """
    length = _float_param(parameters, "length", 80.0)
    diameter = _float_param(parameters, "diameter", 20.0)
    end_diameter = _float_param(parameters, "end_diameter", 15.0)
    end_length = _float_param(parameters, "end_length", 20.0)

    # 几何合法性校验：端部长度必须严格小于总长度，否则主轴段长度非正
    if end_length >= length:
        raise ValueError(
            f"端部长度 {end_length} 必须小于总长度 {length}"
        )

    # 简化建模：主圆柱 + 端部细圆柱
    code = f"""
import cadquery as cq

length = {length}
diameter = {diameter}
end_diameter = {end_diameter}
end_length = {end_length}
main_length = length - end_length

# 主轴段（z: 0 ~ main_length）
main = cq.Workplane("XY").circle(diameter / 2).extrude(main_length)
# 端部轴段（z: main_length ~ length）
end = cq.Workplane("XY").workplane(offset=main_length).circle(
    end_diameter / 2
).extrude(end_length)
result = main.union(end)
"""

    ports = [
        Port(
            name="shaft_axis",
            type="cylindrical",
            geometry={
                "axis_point": [0.0, 0.0, length / 2],
                "axis_dir": [0.0, 0.0, 1.0],
                "radius": diameter / 2,
            },
        ),
        Port(
            name="end_face_a",
            type="planar_face",
            geometry={
                "origin": [0.0, 0.0, 0.0],
                "normal": [0.0, 0.0, -1.0],
            },
        ),
        Port(
            name="end_face_b",
            type="planar_face",
            geometry={
                "origin": [0.0, 0.0, length],
                "normal": [0.0, 0.0, 1.0],
            },
        ),
    ]

    display_name = name or f"阶梯轴 Φ{int(diameter)}×{int(length)}"
    return TypedPart(
        part_id=part_id,
        part_type="shaft",
        name=display_name,
        parameters={
            "length": length, "diameter": diameter,
            "end_diameter": end_diameter, "end_length": end_length,
        },
        ports=ports,
        generator="standard_part",
        standard_part_name="shaft_stepped",
        cadquery_code=code,
        part_number=f"SHAFT-{int(diameter)}x{int(length)}",
        material="45 钢",
        mass=0.2,
        quantity=quantity,
    )


# ===== 工厂 4：法兰盘 =====


@register("flange_plate")
def _flange_plate(
    part_id: str,
    parameters: dict[str, float | str | bool],
    name: str | None,
    quantity: int,
) -> TypedPart:
    """法兰盘。

    参数：
    - outer_diameter: 外径（mm，默认 100）
    - inner_diameter: 内径（mm，默认 50）
    - thickness: 厚度（mm，默认 10）
    - bolt_count: 螺栓孔数（默认 6）
    - bolt_hole_diameter: 螺栓孔径（mm，默认 10）
    - bolt_circle_diameter: 螺栓分布圆直径（mm，默认 75）

    Port：
    - flange_face_a: 法兰面 A（planar_face）
    - flange_face_b: 法兰面 B（planar_face）
    - center_axis: 中心轴线（axis）
    """
    outer_d = _float_param(parameters, "outer_diameter", 100.0)
    inner_d = _float_param(parameters, "inner_diameter", 50.0)
    thickness = _float_param(parameters, "thickness", 10.0)
    bolt_count = int(_float_param(parameters, "bolt_count", 6))
    bolt_hole_d = _float_param(parameters, "bolt_hole_diameter", 10.0)
    bolt_circle_d = _float_param(parameters, "bolt_circle_diameter", 75.0)

    code = f"""
import cadquery as cq
import math

outer_d = {outer_d}
inner_d = {inner_d}
thickness = {thickness}
bolt_count = {bolt_count}
bolt_hole_d = {bolt_hole_d}
bolt_circle_d = {bolt_circle_d}

# 法兰盘主体（环形）
result = cq.Workplane("XY").circle(outer_d / 2).circle(
    inner_d / 2
).extrude(thickness)

# 螺栓孔阵列
bolt_positions = []
for i in range(bolt_count):
    angle = 2 * math.pi * i / bolt_count
    x = (bolt_circle_d / 2) * math.cos(angle)
    y = (bolt_circle_d / 2) * math.sin(angle)
    bolt_positions.append((x, y))

result = result.faces(">Z").workplane().pushPoints(
    bolt_positions
).circle(bolt_hole_d / 2).cutBlind(-thickness)
"""

    ports = [
        Port(
            name="flange_face_a",
            type="planar_face",
            geometry={
                "origin": [0.0, 0.0, 0.0],
                "normal": [0.0, 0.0, -1.0],
            },
        ),
        Port(
            name="flange_face_b",
            type="planar_face",
            geometry={
                "origin": [0.0, 0.0, thickness],
                "normal": [0.0, 0.0, 1.0],
            },
        ),
        Port(
            name="center_axis",
            type="axis",
            geometry={
                "point": [0.0, 0.0, 0.0],
                "direction": [0.0, 0.0, 1.0],
            },
        ),
    ]

    display_name = name or f"法兰盘 Φ{int(outer_d)}×Φ{int(inner_d)}×{int(thickness)}"
    return TypedPart(
        part_id=part_id,
        part_type="flange",
        name=display_name,
        parameters={
            "outer_diameter": outer_d, "inner_diameter": inner_d,
            "thickness": thickness, "bolt_count": bolt_count,
            "bolt_hole_diameter": bolt_hole_d,
            "bolt_circle_diameter": bolt_circle_d,
        },
        ports=ports,
        generator="standard_part",
        standard_part_name="flange_plate",
        cadquery_code=code,
        part_number=f"FLANGE-{int(outer_d)}x{int(inner_d)}",
        material="Q235",
        mass=0.5,
        quantity=quantity,
    )


# ===== 工厂 5：平键（GB/T 1096）=====


@register("key_flat")
def _key_flat(
    part_id: str,
    parameters: dict[str, float | str | bool],
    name: str | None,
    quantity: int,
) -> TypedPart:
    """普通平键（GB/T 1096）。

    参数：
    - length: 长度 L（mm，默认 20）
    - width: 宽度 b（mm，默认 6）
    - height: 高度 h（mm，默认 6）

    Port：
    - top_face: 顶面（planar_face）
    - bottom_face: 底面（planar_face）
    """
    length = _float_param(parameters, "length", 20.0)
    width = _float_param(parameters, "width", 6.0)
    height = _float_param(parameters, "height", 6.0)

    code = f"""
import cadquery as cq

length = {length}
width = {width}
height = {height}

result = cq.Workplane("XY").box(length, width, height)
"""

    ports = [
        Port(
            name="top_face",
            type="planar_face",
            geometry={
                "origin": [0.0, 0.0, height / 2],
                "normal": [0.0, 0.0, 1.0],
            },
        ),
        Port(
            name="bottom_face",
            type="planar_face",
            geometry={
                "origin": [0.0, 0.0, -height / 2],
                "normal": [0.0, 0.0, -1.0],
            },
        ),
    ]

    display_name = name or f"平键 {int(length)}×{int(width)}×{int(height)}"
    return TypedPart(
        part_id=part_id,
        part_type="key",
        name=display_name,
        parameters={"length": length, "width": width, "height": height},
        ports=ports,
        generator="standard_part",
        standard_part_name="key_flat",
        cadquery_code=code,
        part_number=f"GB1096-{int(length)}x{int(width)}",
        material="45 钢",
        mass=0.005,
        quantity=quantity,
    )


# ===== 工厂 6：直齿圆柱齿轮（简化）=====


@register("gear_spur")
def _gear_spur(
    part_id: str,
    parameters: dict[str, float | str | bool],
    name: str | None,
    quantity: int,
) -> TypedPart:
    """直齿圆柱齿轮（简化参数化）。

    参数：
    - module: 模数 m（mm，默认 2）
    - teeth: 齿数 z（默认 20）
    - thickness: 齿宽（mm，默认 15）
    - bore_diameter: 中心孔径（mm，默认 10）

    Port：
    - gear_axis: 齿轮轴线（cylindrical）
    - side_face_a: 侧面 A（planar_face）
    - side_face_b: 侧面 B（planar_face）
    """
    module = _float_param(parameters, "module", 2.0)
    teeth = int(_float_param(parameters, "teeth", 20))
    thickness = _float_param(parameters, "thickness", 15.0)
    bore_d = _float_param(parameters, "bore_diameter", 10.0)

    pitch_diameter = module * teeth
    outer_diameter = pitch_diameter + 2 * module

    # 简化建模：圆柱体 + 中心孔（齿形用外圆柱面近似，实际生产需渐开线齿廓）
    code = f"""
import cadquery as cq
import math

module = {module}
teeth = {teeth}
thickness = {thickness}
bore_d = {bore_d}
outer_d = {outer_diameter}

# 齿轮毛坯（圆柱体 + 中心孔）
result = cq.Workplane("XY").circle(outer_d / 2).circle(
    bore_d / 2
).extrude(thickness)

# 注：齿形简化为外圆柱面，实际生产应使用渐开线齿廓
"""

    ports = [
        Port(
            name="gear_axis",
            type="cylindrical",
            geometry={
                "axis_point": [0.0, 0.0, thickness / 2],
                "axis_dir": [0.0, 0.0, 1.0],
                "radius": bore_d / 2,
            },
        ),
        Port(
            name="side_face_a",
            type="planar_face",
            geometry={
                "origin": [0.0, 0.0, 0.0],
                "normal": [0.0, 0.0, -1.0],
            },
        ),
        Port(
            name="side_face_b",
            type="planar_face",
            geometry={
                "origin": [0.0, 0.0, thickness],
                "normal": [0.0, 0.0, 1.0],
            },
        ),
    ]

    display_name = name or f"齿轮 m{int(module)}z{teeth}"
    return TypedPart(
        part_id=part_id,
        part_type="gear",
        name=display_name,
        parameters={
            "module": module, "teeth": teeth,
            "thickness": thickness, "bore_diameter": bore_d,
        },
        ports=ports,
        generator="standard_part",
        standard_part_name="gear_spur",
        cadquery_code=code,
        part_number=f"GEAR-m{int(module)}z{teeth}",
        material="45 钢",
        mass=0.3,
        quantity=quantity,
    )


# ===== 模块自检 =====


def _self_test() -> dict[str, Any]:
    """离线自检：验证所有工厂可调用且返回合法 TypedPart。"""
    checks: dict[str, bool] = {}
    errors: list[str] = []

    # 工厂注册完整
    expected = {
        "bolt_iso4762", "bearing_6200", "shaft_stepped",
        "flange_plate", "key_flat", "gear_spur",
    }
    checks["factories_registered"] = expected.issubset(set(FACTORIES.keys()))

    # 每个工厂生成 TypedPart
    test_cases = [
        ("bolt_iso4762", "bolt-001", {"m": 8.0, "length": 30.0}),
        ("bearing_6200", "bearing-001", {"outer_diameter": 28.0, "inner_diameter": 12.0, "width": 8.0}),
        ("shaft_stepped", "shaft-001", {"length": 80.0, "diameter": 20.0}),
        ("flange_plate", "flange-001", {"outer_diameter": 100.0, "inner_diameter": 50.0, "thickness": 10.0, "bolt_count": 6}),
        ("key_flat", "key-001", {"length": 20.0, "width": 6.0, "height": 6.0}),
        ("gear_spur", "gear-001", {"module": 2.0, "teeth": 20, "thickness": 15.0}),
    ]
    for factory_name, part_id, params in test_cases:
        try:
            part = create_part(factory_name, part_id, params)
            checks[f"{factory_name}_created"] = part.part_id == part_id
            checks[f"{factory_name}_generator"] = part.generator == "standard_part"
            checks[f"{factory_name}_has_code"] = bool(part.cadquery_code)
            checks[f"{factory_name}_has_ports"] = len(part.ports) > 0
            checks[f"{factory_name}_has_bom"] = (
                part.part_number is not None and part.material is not None
            )
            # 验证 CadQuery 代码含 result 变量
            checks[f"{factory_name}_code_has_result"] = "result" in (part.cadquery_code or "")
            # 验证 Port 几何字段完整（按 PortType）
            for port in part.ports:
                ok_port = _validate_port_geometry(port)
                if not ok_port:
                    errors.append(
                        f"{factory_name} Port {port.name} ({port.type}) 几何字段缺失"
                    )
                    checks[f"{factory_name}_port_{port.name}_geometry"] = False
                else:
                    checks[f"{factory_name}_port_{port.name}_geometry"] = True
        except Exception as e:  # noqa: BLE001
            errors.append(f"{factory_name} 创建失败: {e}")
            checks[f"{factory_name}_created"] = False

    # 未知工厂报错
    try:
        create_part("nonexistent", "x", {})
        checks["unknown_factory_errors"] = False
    except ValueError:
        checks["unknown_factory_errors"] = True

    # 参数缺失使用默认值
    try:
        part = create_part("bolt_iso4762", "bolt-default", {})
        checks["default_params_used"] = part.parameters.get("m") == 8.0
    except Exception:  # noqa: BLE001
        checks["default_params_used"] = False

    ok = all(checks.values())
    return {"ok": ok, "errors": errors, "checks": checks}


def _validate_port_geometry(port: Port) -> bool:
    """校验 Port 几何字段是否按 PortType 完整。"""
    g = port.geometry
    if port.type == "planar_face":
        return "origin" in g and "normal" in g
    if port.type == "cylindrical":
        return "axis_point" in g and "axis_dir" in g and "radius" in g
    if port.type == "circular_edge":
        return "center" in g and "normal" in g and "radius" in g
    if port.type == "linear_edge":
        return "start" in g and "end" in g
    if port.type == "vertex":
        return "point" in g
    if port.type == "axis":
        return "point" in g and "direction" in g
    if port.type == "origin":
        return True
    return False


if __name__ == "__main__":  # pragma: no cover
    import json
    result = _self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    import sys
    sys.exit(0 if result["ok"] else 1)
