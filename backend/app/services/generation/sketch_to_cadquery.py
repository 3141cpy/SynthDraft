"""草图特征 → CadQuery 代码生成（Task 12.2）。

设计原则：
- 简单特征（圆/矩形/多边形）直接生成 CadQuery 拉伸代码
- 复杂特征（hole/chamfer/fillet）在主体上做布尔运算/边操作
- 无法识别时生成占位代码 + warning
- 始终在代码末尾定义 `result` 变量（cq.Workplane）
- 代码注释中标注"草图级精度，需人工校准"

CadQuery API 实测要点（"以瞎猜接口为耻"——所有 API 经实测确认）：
- cq.Workplane("XY").circle(r).extrude(h)  → 圆柱
- cq.Workplane("XY").rect(w, h).extrude(d)  → 长方体
- cq.Workplane("XY").polygon(n, side).extrude(d)  → 正多边形棱柱
- cq.Workplane("XY").box(l, w, h)  → 立方体（占位）
- 主体.faces(">Z").workplane().center(x, y).hole(d)  → 钻孔（d 为直径）
- 主体.edges().chamfer(s)  → 倒角（s 必须小于最短边一半）
- 主体.edges().fillet(r)  → 圆角（r 必须小于最短边一半）

操作顺序（避免 chamfer/fillet 干扰 hole 边）：
1. 主体（circle/rectangle/polygon extrude）
2. chamfer/fillet（仅作用于主体外轮廓边）
3. hole（最后钻孔）
"""
from __future__ import annotations

import sys
import time
import math
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.schemas.sketch import SketchFeature, SketchParseResult
from app.services.generation.sandbox import execute_cadquery_code

log = get_logger(__name__)

# 默认参数（VLM 未识别时使用，保证几何可生成）
_DEFAULT_THICKNESS = 5.0
_DEFAULT_CHAMFER = 1.0
_DEFAULT_FILLET = 1.0
# 占位立方体尺寸
_PLACEHOLDER_SIZE = 10.0


def _to_float(value: Any, default: float = 0.0) -> float:
    """安全转 float。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _radius_from_params(params: dict[str, Any]) -> float:
    """从参数中提取半径（兼容 radius / diameter）。"""
    radius = _to_float(params.get("radius"), 0.0)
    if radius <= 0:
        diameter = _to_float(params.get("diameter"), 0.0)
        if diameter > 0:
            radius = diameter / 2
    return radius


def _thickness_from_params(params: dict[str, Any]) -> float:
    """从参数中提取厚度（兼容 thickness / depth / height）。"""
    thickness = _to_float(params.get("thickness"), 0.0)
    if thickness <= 0:
        thickness = _to_float(params.get("depth"), 0.0)
    if thickness <= 0:
        thickness = _to_float(params.get("height"), 0.0)
    if thickness <= 0:
        thickness = _DEFAULT_THICKNESS
    return thickness


def _gen_circle_code(feat: SketchFeature, var_name: str) -> str | None:
    """生成圆形拉伸代码。"""
    params = feat.parameters or {}
    radius = _radius_from_params(params)
    if radius <= 0:
        return None
    thickness = _thickness_from_params(params)
    return f'{var_name} = cq.Workplane("XY").circle({radius}).extrude({thickness})'


def _gen_rectangle_code(feat: SketchFeature, var_name: str) -> str | None:
    """生成矩形拉伸代码。"""
    params = feat.parameters or {}
    width = _to_float(params.get("width"), 0.0)
    height = _to_float(params.get("height"), 0.0)
    # 兼容 length 字段
    if width <= 0:
        width = _to_float(params.get("length"), 0.0)
    if width <= 0 or height <= 0:
        return None
    thickness = _thickness_from_params(params)
    return f'{var_name} = cq.Workplane("XY").rect({width}, {height}).extrude({thickness})'


def _gen_polygon_code(feat: SketchFeature, var_name: str) -> str | None:
    """生成正多边形拉伸代码。"""
    params = feat.parameters or {}
    sides = int(_to_float(params.get("sides"), 0))
    if sides < 3:
        return None
    side_length = _to_float(params.get("side_length"), 0.0)
    if side_length <= 0:
        return None
    thickness = _thickness_from_params(params)
    # CadQuery polygon(nSides, diameter) 第二参数为外接圆直径（非边长）
    # 由边长换算外接圆直径：diameter = side_length / sin(pi / n_sides)
    diameter = side_length / math.sin(math.pi / sides)
    return f'{var_name} = cq.Workplane("XY").polygon({sides}, {diameter}).extrude({thickness})'


def _gen_hole_code(feat: SketchFeature, current_var: str) -> str | None:
    """生成孔代码（在主体顶面 .hole(d) 钻孔，d 为直径）。

    CadQuery .hole() 实测：接受直径（非半径），从当前 workplane 向下钻孔。
    """
    params = feat.parameters or {}
    radius = _radius_from_params(params)
    if radius <= 0:
        return None
    pos_x = _to_float(params.get("position_x"), 0.0)
    pos_y = _to_float(params.get("position_y"), 0.0)
    diameter = radius * 2
    # 在顶面 center 到指定位置后钻孔
    return (
        f'{current_var} = ({current_var}.faces(">Z").workplane()'
        f".center({pos_x}, {pos_y}).hole({diameter}))"
    )


def _gen_chamfer_code(feat: SketchFeature, current_var: str) -> str | None:
    """生成倒角代码（对所有边倒角）。"""
    params = feat.parameters or {}
    size = _to_float(params.get("size"), _DEFAULT_CHAMFER)
    if size <= 0:
        size = _DEFAULT_CHAMFER
    return f"{current_var} = {current_var}.edges().chamfer({size})"


def _gen_fillet_code(feat: SketchFeature, current_var: str) -> str | None:
    """生成圆角代码（对所有边圆角）。"""
    params = feat.parameters or {}
    radius = _to_float(params.get("radius"), _DEFAULT_FILLET)
    if radius <= 0:
        radius = _DEFAULT_FILLET
    return f"{current_var} = {current_var}.edges().fillet({radius})"


def sketch_features_to_cadquery(parse_result: SketchParseResult) -> str:
    """把草图特征转为 CadQuery Python 代码。

    Args:
        parse_result: 草图解析结果

    Returns:
        CadQuery Python 代码字符串。
        - 末尾定义 `result` 变量（cq.Workplane）
        - 代码注释中标注"草图级精度，需人工校准"
        - 无法识别时生成占位代码
    """
    features = parse_result.features or []
    body_lines: list[str] = [
        "# === 草图级精度，需人工校准 ===",
        "# 此代码由 VLM 草图解析自动生成，尺寸可能不准确",
        "# 依据 spec.md R7：草图精度有限，强制人工校准尺寸环节",
        "import cadquery as cq",
        "",
    ]

    main_var = "result"
    has_main = False

    # 主特征优先（circle/rectangle/polygon），取第一个作为主体
    main_feature_idx = -1
    for i, feat in enumerate(features):
        if feat.feature_type in ("circle", "rectangle", "polygon"):
            main_feature_idx = i
            break

    if main_feature_idx < 0:
        # 无主特征 → 生成占位立方体
        body_lines.append("# 未识别到主体形状（circle/rectangle/polygon），生成占位立方体")
        body_lines.append(
            f'{main_var} = cq.Workplane("XY").box({_PLACEHOLDER_SIZE}, '
            f"{_PLACEHOLDER_SIZE}, {_DEFAULT_THICKNESS})"
        )
        has_main = True
    else:
        feat = features[main_feature_idx]
        if feat.feature_type == "circle":
            code = _gen_circle_code(feat, main_var)
        elif feat.feature_type == "rectangle":
            code = _gen_rectangle_code(feat, main_var)
        elif feat.feature_type == "polygon":
            code = _gen_polygon_code(feat, main_var)
        else:
            code = None

        if code:
            body_lines.append(f"# 主体: {feat.feature_type}")
            body_lines.append(code)
            has_main = True
        else:
            body_lines.append(f"# 主体特征 {feat.feature_type} 参数无效，生成占位立方体")
            body_lines.append(
                f'{main_var} = cq.Workplane("XY").box({_PLACEHOLDER_SIZE}, '
                f"{_PLACEHOLDER_SIZE}, {_DEFAULT_THICKNESS})"
            )
            has_main = True

    # 处理辅助特征：先 chamfer/fillet（避免作用于孔边），再 hole
    for i, feat in enumerate(features):
        if i == main_feature_idx:
            continue
        if feat.feature_type == "chamfer":
            code = _gen_chamfer_code(feat, main_var)
            if code:
                body_lines.append("# 倒角")
                body_lines.append(code)
        elif feat.feature_type == "fillet":
            code = _gen_fillet_code(feat, main_var)
            if code:
                body_lines.append("# 圆角")
                body_lines.append(code)

    for i, feat in enumerate(features):
        if i == main_feature_idx:
            continue
        if feat.feature_type == "hole":
            code = _gen_hole_code(feat, main_var)
            if code:
                body_lines.append("# 孔")
                body_lines.append(code)
        elif feat.feature_type in ("line", "arc", "unknown"):
            # 线/弧/未知暂不参与 3D 生成（仅 2D 信息）
            body_lines.append(f"# 特征 {feat.feature_type} 不参与 3D 生成（仅 2D 信息）")

    # 保险：确保末尾有 result 变量
    if not has_main:
        body_lines.append(
            f'{main_var} = cq.Workplane("XY").box({_PLACEHOLDER_SIZE}, '
            f"{_PLACEHOLDER_SIZE}, {_DEFAULT_THICKNESS})"
        )

    return "\n".join(body_lines)


def sketch_to_dxf_via_cadquery(
    parse_result: SketchParseResult,
    output_path: Path,
) -> Path:
    """草图 → CadQuery → DXF 文件。

    复用 sandbox.execute_cadquery_code 执行生成的代码。

    Args:
        parse_result: 草图解析结果
        output_path: 输出 DXF 文件路径（其父目录作为沙箱输出目录）

    Returns:
        实际生成的 DXF 文件路径

    Raises:
        RuntimeError: 沙箱执行未生成 DXF 文件
    """
    output_path = Path(output_path)
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    code = sketch_features_to_cadquery(parse_result)
    log.info(
        "sketch_to_cad.execute.start",
        code_len=len(code),
        output=str(output_path),
    )

    t0 = time.monotonic()
    # 沙箱执行（DXF 为主格式，沙箱会同时生成 STEP/STL 用于校验）
    result = execute_cadquery_code(
        code=code,
        output_dir=output_dir,
        timeout=30,
        output_format="dxf",
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # 查找生成的 DXF 文件
    dxf_files = [
        Path(p) for p in result.output_files if p.lower().endswith(".dxf")
    ]
    if dxf_files:
        actual_dxf = dxf_files[0]
        # 如果实际生成路径与预期不同，复制到预期路径
        if actual_dxf != output_path and actual_dxf.exists():
            import shutil

            shutil.copy2(actual_dxf, output_path)
        log.info(
            "sketch_to_cad.dxf_generated",
            output=str(output_path),
            elapsed_ms=elapsed_ms,
            success=result.success,
        )
        return output_path

    log.warning(
        "sketch_to_cad.no_dxf",
        success=result.success,
        stderr=result.stderr[:500],
        output_files=result.output_files,
    )
    raise RuntimeError(
        f"CadQuery 沙箱执行未生成 DXF 文件（success={result.success}）: "
        f"{result.stderr[:300]}"
    )


# ===== 自检（"以覆盖测试为荣"） =====


def self_test() -> dict[str, Any]:
    """自检：构造 SketchParseResult → 生成代码 → 沙箱执行 → 验证产出。

    实测要求：
    - 圆形 + 孔 → 生成代码 + 沙箱执行 + DXF 文件
    - 矩形 + 倒角 → 生成代码 + 沙箱执行 + STEP 文件
    - 空特征 → 占位代码
    """
    import tempfile

    result: dict[str, Any] = {"checks": {}, "scenarios": []}

    # 场景 1：圆形主体 + 孔 → 代码生成 + 沙箱执行
    try:
        parse_result = SketchParseResult(
            features=[
                SketchFeature(
                    feature_type="circle",
                    parameters={"radius": 30, "thickness": 10},
                    confidence=0.9,
                ),
                SketchFeature(
                    feature_type="hole",
                    parameters={
                        "radius": 5,
                        "position_x": 0,
                        "position_y": 0,
                        "depth": 10,
                    },
                    confidence=0.85,
                ),
            ],
            overall_shape="带孔圆盘",
            vlm_model="test",
        )
        code = sketch_features_to_cadquery(parse_result)
        result["scenarios"].append(
            {
                "name": "场景1: 圆形+孔 代码生成",
                "code": code,
                "passed": (
                    "import cadquery" in code
                    and "result =" in code
                    and "circle(" in code
                    and "hole(" in code
                ),
            }
        )

        # 沙箱执行（DXF 输出）
        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td) / "out1"
            output_dir.mkdir()
            exec_result = execute_cadquery_code(
                code=code,
                output_dir=output_dir,
                timeout=30,
                output_format="dxf",
            )
            result["scenarios"].append(
                {
                    "name": "场景1: 沙箱执行（DXF）",
                    "success": exec_result.success,
                    "output_files": exec_result.output_files,
                    "elapsed_ms": exec_result.elapsed_ms,
                    "stderr": (
                        exec_result.stderr[:300] if not exec_result.success else ""
                    ),
                    "passed": (
                        exec_result.success
                        and any(p.endswith(".dxf") for p in exec_result.output_files)
                    ),
                }
            )
    except Exception as e:  # noqa: BLE001
        result["scenarios"].append(
            {
                "name": "场景1",
                "passed": False,
                "error": f"{type(e).__name__}: {e}",
            }
        )

    # 场景 2：矩形主体 + 倒角 → STEP 输出
    try:
        parse_result = SketchParseResult(
            features=[
                SketchFeature(
                    feature_type="rectangle",
                    parameters={"width": 60, "height": 40, "thickness": 8},
                    confidence=0.9,
                ),
                SketchFeature(
                    feature_type="chamfer",
                    parameters={"size": 1.0},
                    confidence=0.8,
                ),
            ],
            overall_shape="矩形板",
            vlm_model="test",
        )
        code = sketch_features_to_cadquery(parse_result)

        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td) / "out2"
            output_dir.mkdir()
            exec_result = execute_cadquery_code(
                code=code,
                output_dir=output_dir,
                timeout=30,
                output_format="step",
            )
            result["scenarios"].append(
                {
                    "name": "场景2: 矩形+倒角 沙箱执行（STEP）",
                    "success": exec_result.success,
                    "output_files": exec_result.output_files,
                    "passed": exec_result.success,
                }
            )
    except Exception as e:  # noqa: BLE001
        result["scenarios"].append(
            {
                "name": "场景2",
                "passed": False,
                "error": f"{type(e).__name__}: {e}",
            }
        )

    # 场景 3：无主体特征 → 占位代码
    try:
        parse_result = SketchParseResult(
            features=[],
            overall_shape="",
            vlm_model="test",
        )
        code = sketch_features_to_cadquery(parse_result)
        result["scenarios"].append(
            {
                "name": "场景3: 空特征 占位代码",
                "code": code,
                "passed": "box(" in code and "result =" in code,
            }
        )
    except Exception as e:  # noqa: BLE001
        result["scenarios"].append(
            {
                "name": "场景3",
                "passed": False,
                "error": str(e),
            }
        )

    return result


if __name__ == "__main__":
    print("=" * 70)
    print("草图→CadQuery 代码生成自检（Task 12.2）")
    print("=" * 70)

    report = self_test()
    for sc in report["scenarios"]:
        mark = "[PASS]" if sc.get("passed") else "[FAIL]"
        print(f"\n{mark} {sc['name']}")
        for k, v in sc.items():
            if k not in ("name", "passed"):
                if k == "code" and isinstance(v, str):
                    print(f"  code:")
                    for line in v.split("\n"):
                        print(f"    {line}")
                else:
                    print(f"  {k}: {v}")

    print("\n" + "=" * 70)
    all_passed = all(sc.get("passed") for sc in report["scenarios"])
    print(f"{'全部场景通过 ✅' if all_passed else '存在失败场景 ❌'}")
    sys.exit(0 if all_passed else 1)
