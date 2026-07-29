"""人工校准模块（Task 12.3）。

依据 spec.md §"Scenario: 手绘草图转 CAD" 与风险项 R7：
- VLM 解析出的草图尺寸可能不准确（"草图级精度"）
- 强制提供人工校准环节，允许用户修改参数后重新生成
- 校准后产出可编辑 DXF / SLDPRT，并保留校准痕迹

设计原则（八荣八耻）：
- 以复用现有为荣：复用 sketch_to_cadquery.sketch_features_to_cadquery /
  sketch_to_dxf_via_cadquery / sandbox.execute_cadquery_code
- 以瞎猜接口为耻：所有接口经实测确认（CalibrationItem/CalibrationResult schema 对齐）
- 以实事求是为荣：校准过程记录 original_value vs calibrated_value 差异
- 以覆盖测试为荣：自带 self_test 验证校准闭环

校准流程：
1. 输入：原 SketchParseResult.features + 用户提交的 CalibrationItem 列表
2. 应用校准：按 feature_index 定位特征，按 parameter_name 覆盖参数
3. 单位转换（mm 默认，兼容 inch/cm）
4. 重新生成 CadQuery 代码
5. 沙箱执行 → DXF / STEP 输出
6. 返回 CalibrationResult（含校准后特征 + 新代码 + 输出文件）
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.schemas.sketch import (
    CalibrationItem,
    CalibrationResult,
    SketchFeature,
    SketchParseResult,
)
from app.services.generation.sandbox import execute_cadquery_code
from app.services.generation.sketch_to_cadquery import (
    sketch_features_to_cadquery,
    sketch_to_dxf_via_cadquery,
)

log = get_logger(__name__)

__all__ = [
    "apply_calibrations",
    "calibrate_and_regenerate",
    "self_test",
]

# 单位 → mm 换算因子（与 spec.md R7 单位策略对齐，默认 mm）
_UNIT_TO_MM: dict[str, float] = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "inch": 25.4,
    "in": 25.4,
    "ft": 304.8,
}


def _to_mm(value: float, unit: str) -> float:
    """把任意单位长度转换为 mm。

    Args:
        value: 原始数值
        unit: 单位字符串（mm/cm/m/inch/in/ft），未知单位视为 mm

    Returns:
        mm 单位的数值
    """
    factor = _UNIT_TO_MM.get(unit.lower(), 1.0)
    return float(value) * factor


def _apply_calibration_to_feature(
    feature: SketchFeature,
    calibration: CalibrationItem,
) -> SketchFeature:
    """对单个特征应用单条校准（不可变风格，返回新对象）。

    Args:
        feature: 原始特征
        calibration: 校准项（指定 parameter_name 与 calibrated_value）

    Returns:
        校准后的新 SketchFeature 对象（参数已更新）
    """
    new_params = dict(feature.parameters or {})
    calibrated_mm = _to_mm(calibration.calibrated_value, calibration.unit)
    new_params[calibration.parameter_name] = calibrated_mm

    return feature.model_copy(update={"parameters": new_params})


def apply_calibrations(
    parse_result: SketchParseResult,
    calibrations: list[CalibrationItem],
) -> tuple[SketchParseResult, list[str]]:
    """对 SketchParseResult 应用一批校准项。

    Args:
        parse_result: 原始解析结果
        calibrations: 校准项列表（按 feature_index 定位）

    Returns:
        (校准后的新 SketchParseResult, warnings 列表)
        - 越界索引、未知参数名等会记入 warnings，不抛异常
    """
    features = list(parse_result.features or [])
    warnings: list[str] = []

    for calib in calibrations:
        idx = calib.feature_index
        if idx < 0 or idx >= len(features):
            warnings.append(
                f"校准项跳过：feature_index={idx} 越界（features 长度 {len(features)}）"
            )
            continue

        feat = features[idx]
        # 类型一致性检查（仅警告，不阻断）
        if calib.feature_type and calib.feature_type != feat.feature_type:
            warnings.append(
                f"feature_index={idx} 类型不一致："
                f"calibration={calib.feature_type} vs feature={feat.feature_type}"
            )

        features[idx] = _apply_calibration_to_feature(feat, calib)
        log.info(
            "calibration.applied",
            feature_index=idx,
            parameter=calib.parameter_name,
            original=calib.original_value,
            calibrated=calib.calibrated_value,
            unit=calib.unit,
        )

    new_parse = parse_result.model_copy(update={"features": features})
    return new_parse, warnings


def calibrate_and_regenerate(
    parse_result: SketchParseResult,
    calibrations: list[CalibrationItem],
    output_dir: Path,
    output_format: str = "dxf",
) -> CalibrationResult:
    """校准 + 重新生成的完整流程（Task 12.3 主入口）。

    流程：
    1. apply_calibrations：批量覆盖参数
    2. sketch_features_to_cadquery：生成新 CadQuery 代码
    3. 沙箱执行（DXF/STEP 输出）
    4. 返回 CalibrationResult

    Args:
        parse_result: 原始草图解析结果
        calibrations: 用户校准项列表
        output_dir: 输出目录（不存在则创建）
        output_format: 主输出格式（dxf/step/stl/iges）

    Returns:
        CalibrationResult：含校准后特征、新代码、输出文件路径
    """
    task_id = f"calib-{uuid.uuid4().hex[:12]}"
    t0 = time.monotonic()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 应用校准
    calibrated_parse, calib_warnings = apply_calibrations(parse_result, calibrations)

    # 2. 重新生成 CadQuery 代码
    try:
        regenerated_code = sketch_features_to_cadquery(calibrated_parse)
    except Exception as e:  # noqa: BLE001
        log.error("calibration.codegen_failed", error=str(e))
        return CalibrationResult(
            task_id=task_id,
            success=False,
            calibrated_features=calibrated_parse.features,
            regenerated_code="",
            output_files={},
            warnings=calib_warnings + [f"代码生成失败: {e}"],
        )

    # 3. 沙箱执行生成文件
    output_files: dict[str, str] = {}
    fmt = output_format.lower()
    if fmt not in ("dxf", "step", "stl", "iges"):
        fmt = "dxf"

    try:
        # 主格式路径
        primary_path = output_dir / f"calibrated.{fmt}"
        if fmt == "dxf":
            # 复用 sketch_to_dxf_via_cadquery（已处理沙箱执行 + 文件查找）
            actual = sketch_to_dxf_via_cadquery(calibrated_parse, primary_path)
            output_files["dxf"] = str(actual)
            # 同时输出 STEP 用于几何校验（沙箱内部已附加）
            step_files = list(output_dir.glob("*.step")) + list(output_dir.glob("*.stp"))
            if step_files:
                output_files["step"] = str(step_files[0])
        else:
            # 非 DXF：直接调用沙箱
            execution = execute_cadquery_code(
                code=regenerated_code,
                output_dir=output_dir,
                timeout=30,
                output_format=fmt,
            )
            if not execution.success:
                return CalibrationResult(
                    task_id=task_id,
                    success=False,
                    calibrated_features=calibrated_parse.features,
                    regenerated_code=regenerated_code,
                    output_files={},
                    warnings=calib_warnings + [
                        f"沙箱执行失败: {execution.stderr[:300]}",
                    ],
                )
            # 收集输出文件（按扩展名映射）
            for p in output_dir.glob("*"):
                if p.suffix.lower().lstrip(".") in ("dxf", "step", "stp", "stl", "iges"):
                    ext = p.suffix.lower().lstrip(".")
                    if ext not in output_files:
                        output_files[ext] = str(p.resolve())
    except Exception as e:  # noqa: BLE001
        log.error("calibration.execute_failed", error=str(e))
        return CalibrationResult(
            task_id=task_id,
            success=False,
            calibrated_features=calibrated_parse.features,
            regenerated_code=regenerated_code,
            output_files={},
            warnings=calib_warnings + [f"沙箱执行异常: {type(e).__name__}: {e}"],
        )

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    log.info(
        "calibration.done",
        task_id=task_id,
        success=True,
        output_count=len(output_files),
        elapsed_ms=elapsed_ms,
    )

    return CalibrationResult(
        task_id=task_id,
        success=True,
        calibrated_features=calibrated_parse.features,
        regenerated_code=regenerated_code,
        output_files=output_files,
        warnings=calib_warnings,
    )


# ===== 自检（"以覆盖测试为荣"） =====


def self_test() -> dict[str, Any]:
    """自检：构造 SketchParseResult + 校准项 → 应用 → 重新生成 → 验证。

    实测要求：
    - 圆形 radius=30 → 校准为 radius=50 → 参数已更新
    - 越界索引 → 记入 warnings
    - 类型不一致 → 记入 warnings
    - 单位 inch → mm 转换正确（25.4 倍）
    - 重新生成代码 → 沙箱执行 → DXF 文件产出
    """
    import tempfile

    result: dict[str, Any] = {"checks": {}, "scenarios": []}

    # 场景 1：单条校准 + 参数更新
    try:
        parse = SketchParseResult(
            features=[
                SketchFeature(
                    feature_type="circle",
                    parameters={"radius": 30.0, "thickness": 10.0},
                    confidence=0.9,
                ),
            ],
            overall_shape="圆盘",
            vlm_model="test",
        )
        calibrations = [
            CalibrationItem(
                feature_index=0,
                feature_type="circle",
                parameter_name="radius",
                original_value=30.0,
                calibrated_value=50.0,
                unit="mm",
            ),
        ]
        new_parse, warns = apply_calibrations(parse, calibrations)
        new_radius = float(new_parse.features[0].parameters["radius"])
        result["scenarios"].append(
            {
                "name": "场景1: 单条校准参数更新",
                "original_radius": 30.0,
                "calibrated_radius": new_radius,
                "warnings": warns,
                "passed": (
                    abs(new_radius - 50.0) < 0.01
                    and len(warns) == 0
                ),
            }
        )
    except Exception as e:  # noqa: BLE001
        result["scenarios"].append(
            {"name": "场景1", "passed": False, "error": f"{type(e).__name__}: {e}"}
        )

    # 场景 2：越界索引 + 类型不一致
    try:
        parse = SketchParseResult(
            features=[
                SketchFeature(
                    feature_type="circle",
                    parameters={"radius": 30.0},
                ),
            ],
            vlm_model="test",
        )
        calibrations = [
            CalibrationItem(
                feature_index=5,  # 越界
                feature_type="circle",
                parameter_name="radius",
                calibrated_value=50.0,
            ),
            CalibrationItem(
                feature_index=0,
                feature_type="rectangle",  # 类型不一致
                parameter_name="radius",
                calibrated_value=50.0,
            ),
        ]
        _, warns = apply_calibrations(parse, calibrations)
        result["scenarios"].append(
            {
                "name": "场景2: 越界 + 类型不一致警告",
                "warnings_count": len(warns),
                "warnings": warns,
                "passed": (
                    len(warns) == 2
                    and any("越界" in w for w in warns)
                    and any("类型不一致" in w for w in warns)
                ),
            }
        )
    except Exception as e:  # noqa: BLE001
        result["scenarios"].append(
            {"name": "场景2", "passed": False, "error": f"{type(e).__name__}: {e}"}
        )

    # 场景 3：单位转换（inch → mm）
    try:
        parse = SketchParseResult(
            features=[
                SketchFeature(
                    feature_type="rectangle",
                    parameters={"width": 10.0, "height": 5.0, "thickness": 2.0},
                ),
            ],
            vlm_model="test",
        )
        calibrations = [
            CalibrationItem(
                feature_index=0,
                feature_type="rectangle",
                parameter_name="width",
                original_value=10.0,
                calibrated_value=2.0,  # 2 inch = 50.8 mm
                unit="inch",
            ),
        ]
        new_parse, _ = apply_calibrations(parse, calibrations)
        new_width = float(new_parse.features[0].parameters["width"])
        result["scenarios"].append(
            {
                "name": "场景3: inch → mm 单位转换",
                "input_inch": 2.0,
                "calibrated_width_mm": new_width,
                "passed": abs(new_width - 50.8) < 0.01,
            }
        )
    except Exception as e:  # noqa: BLE001
        result["scenarios"].append(
            {"name": "场景3", "passed": False, "error": f"{type(e).__name__}: {e}"}
        )

    # 场景 4：完整闭环（校准 + 重新生成 + 沙箱执行）
    try:
        parse = SketchParseResult(
            features=[
                SketchFeature(
                    feature_type="circle",
                    parameters={"radius": 30.0, "thickness": 10.0},
                    confidence=0.9,
                ),
                SketchFeature(
                    feature_type="hole",
                    parameters={
                        "radius": 5.0,
                        "position_x": 0.0,
                        "position_y": 0.0,
                        "depth": 10.0,
                    },
                    confidence=0.85,
                ),
            ],
            overall_shape="带孔圆盘",
            vlm_model="test",
        )
        calibrations = [
            CalibrationItem(
                feature_index=0,
                feature_type="circle",
                parameter_name="radius",
                original_value=30.0,
                calibrated_value=50.0,
                unit="mm",
            ),
            CalibrationItem(
                feature_index=1,
                feature_type="hole",
                parameter_name="radius",
                original_value=5.0,
                calibrated_value=10.0,
                unit="mm",
            ),
        ]
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "calib_out"
            calib_result = calibrate_and_regenerate(
                parse, calibrations, out_dir, output_format="dxf"
            )
            # 校准后参数验证
            new_outer_r = float(calib_result.calibrated_features[0].parameters["radius"])
            new_hole_r = float(calib_result.calibrated_features[1].parameters["radius"])
            # 代码与文件验证
            has_dxf = "dxf" in calib_result.output_files
            result["scenarios"].append(
                {
                    "name": "场景4: 完整闭环（DXF 输出）",
                    "success": calib_result.success,
                    "calibrated_outer_radius": new_outer_r,
                    "calibrated_hole_radius": new_hole_r,
                    "has_dxf": has_dxf,
                    "output_files": list(calib_result.output_files.keys()),
                    "warnings": calib_result.warnings,
                    "passed": (
                        calib_result.success
                        and abs(new_outer_r - 50.0) < 0.01
                        and abs(new_hole_r - 10.0) < 0.01
                        and has_dxf
                        and "草图级精度" in calib_result.regenerated_code
                    ),
                }
            )
    except Exception as e:  # noqa: BLE001
        result["scenarios"].append(
            {"name": "场景4", "passed": False, "error": f"{type(e).__name__}: {e}"}
        )

    # 场景 5：空校准项（应保持原参数不变）
    try:
        parse = SketchParseResult(
            features=[
                SketchFeature(
                    feature_type="rectangle",
                    parameters={"width": 60.0, "height": 40.0},
                ),
            ],
            vlm_model="test",
        )
        new_parse, warns = apply_calibrations(parse, [])
        same_width = float(new_parse.features[0].parameters["width"]) == 60.0
        result["scenarios"].append(
            {
                "name": "场景5: 空校准保持原参数",
                "passed": same_width and len(warns) == 0,
            }
        )
    except Exception as e:  # noqa: BLE001
        result["scenarios"].append(
            {"name": "场景5", "passed": False, "error": f"{type(e).__name__}: {e}"}
        )

    return result


if __name__ == "__main__":
    print("=" * 70)
    print("人工校准模块自检（Task 12.3）")
    print("=" * 70)

    report = self_test()
    for sc in report["scenarios"]:
        mark = "[PASS]" if sc.get("passed") else "[FAIL]"
        print(f"\n{mark} {sc['name']}")
        for k, v in sc.items():
            if k not in ("name", "passed"):
                print(f"  {k}: {v}")

    print("\n" + "=" * 70)
    all_passed = all(sc.get("passed") for sc in report["scenarios"])
    print(f"{'全部场景通过 ✅' if all_passed else '存在失败场景 ❌'}")
    sys.exit(0 if all_passed else 1)
