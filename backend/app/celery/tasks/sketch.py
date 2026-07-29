"""草图转 CAD Celery 任务（Task 12.4）。

实现"草图 → VLM 解析 → CadQuery 代码 → DXF/STEP 输出"完整管线，
并提供人工校准闭环（基于原解析结果 + 校准项重新生成）。

任务清单（2 个）：
1. ``run_sketch_to_cad``     草图 → CAD（VLM 解析 + 代码生成 + 沙箱执行）
2. ``run_sketch_calibration`` 人工校准 → 重新生成（基于原解析结果应用校准项）

依据 spec.md §"Scenario: 手绘草图转 CAD" 与风险项 R7：
- 强制标注 ``precision_level=sketch_level``，提示用户人工校准尺寸
- VLM 不可用时降级返回空 features + warning（不抛异常）
- 沙箱执行失败仍返回结果（success=False），便于前端展示错误并触发校准流程

设计原则（八荣八耻）：
- 以复用现有为荣：复用 sketch_parser.parse_sketch /
  sketch_to_cadquery.sketch_features_to_cadquery / sketch_to_dxf_via_cadquery /
  calibration.calibrate_and_regenerate
- 以瞎猜接口为耻：所有接口经实测确认（SketchTaskResult/CalibrationResult schema 对齐）
- 以实事求是为荣：始终标注草图级精度，不掩盖 VLM 不可用情况
- 以不修改稳定文件为荣：新增独立任务模块，不修改现有 generations/reviews 任务

队列路由（见 app/celery_app.py task_routes）：
    "app.celery.tasks.sketch.*": {"queue": "sketch"}

启动 Worker：
    celery -A app.celery_app worker -Q sketch -c 1 --without-gossip
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from app.celery.base import BaseTask
from app.celery_app import celery_app
from app.config import settings
from app.logging import get_logger
from app.schemas.sketch import (
    CalibrationItem,
    CalibrationResult,
    SketchFeature,
    SketchParseResult,
    SketchTaskResult,
)
from app.services.generation.calibration import calibrate_and_regenerate
from app.services.generation.sketch_parser import parse_sketch
from app.services.generation.sketch_to_cadquery import (
    sketch_features_to_cadquery,
    sketch_to_dxf_via_cadquery,
)
from app.utils.path_safety import resolve_within_roots

log = get_logger(__name__)

# 上传根目录（与 reviews/generations 任务对齐）
_LOCAL_UPLOAD_DIR = Path(settings.UPLOAD_DIR).resolve()

# 输出根目录（草图产物）
_SKETCH_OUTPUT_ROOT = _LOCAL_UPLOAD_DIR / "sketches"

# 图片查找允许的根目录（上传目录 + 开发态 fixtures）
_IMAGE_ROOTS: list[Path] = [
    _LOCAL_UPLOAD_DIR,
    Path("./tests/fixtures").resolve(),
]


# ===== 工具函数 =====


def _resolve_image_path(file_key: str) -> Path:
    """解析草图 file_key 为本地图片路径。

    使用 resolve_within_roots 在允许根目录内查找，拒绝绝对路径与穿越攻击
    （Finding 6）。文件未找到或路径非法时返回安全占位路径（仅取文件名，
    无穿越风险），由调用方 ``is_file()`` 检查处理。
    """
    try:
        return resolve_within_roots(file_key, _IMAGE_ROOTS)
    except (FileNotFoundError, ValueError):
        return _LOCAL_UPLOAD_DIR / Path(file_key).name


def _ensure_output_dir(task_id: str) -> Path:
    """为单次任务创建输出目录。"""
    out_dir = _SKETCH_OUTPUT_ROOT / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _fetch_sketch_parse_result(sketch_task_id: str) -> dict[str, Any] | None:
    """从 Celery result backend 读取原草图任务的解析结果。

    Args:
        sketch_task_id: 原 run_sketch_to_cad 任务 ID

    Returns:
        SketchTaskResult dict（含 parse_result），或 None
    """
    try:
        async_result = celery_app.AsyncResult(sketch_task_id)
        if async_result.state != "SUCCESS":
            log.warning(
                "sketch.fetch_parse.not_ready",
                sketch_task_id=sketch_task_id,
                state=async_result.state,
            )
            return None
        result = async_result.result
        if isinstance(result, dict):
            return result
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        return None
    except Exception as e:  # noqa: BLE001
        log.warning(
            "sketch.fetch_parse.failed",
            sketch_task_id=sketch_task_id,
            error=str(e),
        )
        return None


# ===== 任务 1：run_sketch_to_cad =====


@celery_app.task(
    name="app.celery.tasks.sketch.run_sketch_to_cad",
    bind=True,
    base=BaseTask,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
    time_limit=300,        # 硬超时 5 分钟（VLM 推理 + 沙箱执行）
    soft_time_limit=270,   # 软超时 4.5 分钟
)
def run_sketch_to_cad(
    self: BaseTask,
    image_key: str,
    user_id: str = "anonymous",
    output_format: str = "dxf",
) -> dict[str, Any]:
    """草图转 CAD 任务入口（Task 12 主流程）。

    流程：
    1. 解析草图 file_key → 本地图片路径
    2. parse_sketch：VLM 提取几何特征
    3. sketch_features_to_cadquery：生成 CadQuery 代码（含"草图级精度"标注）
    4. sketch_to_dxf_via_cadquery：沙箱执行 → DXF/STEP 输出
    5. 返回 SketchTaskResult（precision_level=sketch_level 强制）

    Args:
        image_key: 草图图片 file_key（上传后获得，或绝对路径）
        user_id: 提交用户 ID
        output_format: 主输出格式（dxf/step/stl/iges）

    Returns:
        SketchTaskResult dict
    """
    task_id = self.request.id or "unknown"
    t_start = time.perf_counter()
    log.info(
        "sketch.task.start",
        task_id=task_id,
        image_key=image_key,
        user=user_id,
        output_format=output_format,
    )

    # 1. 解析图片路径
    image_path = _resolve_image_path(image_key)
    if not image_path.is_file():
        # 文件不存在 → 返回失败结果（不抛异常，便于前端处理）
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        result = SketchTaskResult(
            task_id=task_id,
            success=False,
            precision_level="sketch_level",
            parse_result=SketchParseResult(
                warnings=[f"草图图片不存在: {image_key}"],
            ),
            generated_code="",
            output_files=[],
            output_format=output_format,
            warnings=[f"草图图片不存在: {image_key}"],
            metadata={
                "user_id": user_id,
                "image_key": image_key,
                "elapsed_ms": elapsed_ms,
                "error": "image_not_found",
            },
        )
        return result.model_dump(mode="json")

    # 2. VLM 解析草图
    try:
        parse_result = parse_sketch(image_path)
    except Exception as e:  # noqa: BLE001
        log.error(
            "sketch.task.parse_failed",
            task_id=task_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        result = SketchTaskResult(
            task_id=task_id,
            success=False,
            precision_level="sketch_level",
            parse_result=SketchParseResult(
                warnings=[f"VLM 解析异常: {type(e).__name__}: {e}"],
            ),
            generated_code="",
            output_files=[],
            output_format=output_format,
            warnings=[f"VLM 解析异常: {type(e).__name__}: {e}"],
            metadata={
                "user_id": user_id,
                "image_key": image_key,
                "elapsed_ms": elapsed_ms,
                "error": "parse_failed",
            },
        )
        return result.model_dump(mode="json")

    log.info(
        "sketch.task.parse_done",
        task_id=task_id,
        features_count=len(parse_result.features),
        vlm_model=parse_result.vlm_model,
        overall_shape=parse_result.overall_shape,
    )

    # 3. 生成 CadQuery 代码
    try:
        generated_code = sketch_features_to_cadquery(parse_result)
    except Exception as e:  # noqa: BLE001
        log.error(
            "sketch.task.codegen_failed",
            task_id=task_id,
            error=str(e),
        )
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        result = SketchTaskResult(
            task_id=task_id,
            success=False,
            precision_level="sketch_level",
            parse_result=parse_result,
            generated_code="",
            output_files=[],
            output_format=output_format,
            warnings=parse_result.warnings + [f"代码生成失败: {e}"],
            metadata={
                "user_id": user_id,
                "image_key": image_key,
                "elapsed_ms": elapsed_ms,
                "error": "codegen_failed",
            },
        )
        return result.model_dump(mode="json")

    # 4. 沙箱执行 → DXF / STEP
    out_dir = _ensure_output_dir(task_id)
    fmt = output_format.lower()
    if fmt not in ("dxf", "step", "stl", "iges"):
        fmt = "dxf"

    output_files: list[str] = []
    execute_warnings: list[str] = []
    success = True
    if parse_result.features:
        # 有特征才执行（无特征时跳过沙箱，避免无意义报错）
        try:
            primary_path = out_dir / f"sketch_output.{fmt}"
            if fmt == "dxf":
                actual = sketch_to_dxf_via_cadquery(parse_result, primary_path)
                output_files.append(str(actual))
                # 沙箱会同时生成 STEP（用于几何校验）
                for step_p in out_dir.glob("*.step"):
                    output_files.append(str(step_p.resolve()))
                    break
                for stl_p in out_dir.glob("*.stl"):
                    output_files.append(str(stl_p.resolve()))
                    break
            else:
                # 非 DXF：直接调用沙箱（复用 sketch_to_dxf_via_cadquery 内部逻辑）
                # 仍然先尝试 DXF 路径，再用 sandbox 生成其他格式
                from app.services.generation.sandbox import execute_cadquery_code

                execution = execute_cadquery_code(
                    code=generated_code,
                    output_dir=out_dir,
                    timeout=30,
                    output_format=fmt,
                )
                if execution.success:
                    output_files.extend(execution.output_files)
                else:
                    success = False
                    execute_warnings.append(
                        f"沙箱执行失败: {execution.stderr[:300]}"
                    )
        except Exception as e:  # noqa: BLE001
            log.error(
                "sketch.task.execute_failed",
                task_id=task_id,
                error=str(e),
            )
            success = False
            execute_warnings.append(f"沙箱执行异常: {type(e).__name__}: {e}")
    else:
        execute_warnings.append("VLM 未识别到几何特征，跳过沙箱执行")

    elapsed_ms = int((time.perf_counter() - t_start) * 1000)
    all_warnings = list(parse_result.warnings) + execute_warnings

    result = SketchTaskResult(
        task_id=task_id,
        success=success,
        precision_level="sketch_level",  # 强制草图级精度（spec.md R7）
        parse_result=parse_result,
        generated_code=generated_code,
        output_files=output_files,
        output_format=fmt,
        warnings=all_warnings,
        metadata={
            "user_id": user_id,
            "image_key": image_key,
            "image_path": str(image_path),
            "vlm_model": parse_result.vlm_model,
            "features_count": len(parse_result.features),
            "overall_shape": parse_result.overall_shape,
            "dimensions_hint": parse_result.dimensions_hint,
            "elapsed_ms": elapsed_ms,
            "output_dir": str(out_dir),
        },
    )

    log.info(
        "sketch.task.done",
        task_id=task_id,
        success=success,
        features_count=len(parse_result.features),
        output_count=len(output_files),
        elapsed_ms=elapsed_ms,
    )
    return result.model_dump(mode="json")


# ===== 任务 2：run_sketch_calibration =====


@celery_app.task(
    name="app.celery.tasks.sketch.run_sketch_calibration",
    bind=True,
    base=BaseTask,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=2,
    acks_late=True,
    time_limit=120,        # 校准 + 重新生成较快，2 分钟足够
    soft_time_limit=100,
)
def run_sketch_calibration(
    self: BaseTask,
    sketch_task_id: str,
    calibrations: list[dict[str, Any]],
    user_id: str = "anonymous",
    output_format: str = "dxf",
) -> dict[str, Any]:
    """人工校准 + 重新生成任务（Task 12.3）。

    流程：
    1. 从 Celery result backend 读取原草图任务的 SketchTaskResult
    2. 提取 parse_result，构造 CalibrationItem 列表
    3. 调用 calibrate_and_regenerate：应用校准 + 重新生成代码 + 沙箱执行
    4. 返回 CalibrationResult

    Args:
        sketch_task_id: 原 run_sketch_to_cad 任务 ID
        calibrations: 校准项列表（dict 形式，符合 CalibrationItem schema）
        user_id: 提交用户 ID
        output_format: 主输出格式

    Returns:
        CalibrationResult dict
    """
    task_id = self.request.id or "unknown"
    t_start = time.perf_counter()
    log.info(
        "sketch.calibration.start",
        task_id=task_id,
        sketch_task_id=sketch_task_id,
        calibrations_count=len(calibrations),
        user=user_id,
    )

    # 1. 读取原草图任务结果
    original_dict = _fetch_sketch_parse_result(sketch_task_id)
    if original_dict is None:
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        result = CalibrationResult(
            task_id=task_id,
            success=False,
            calibrated_features=[],
            regenerated_code="",
            output_files={},
            warnings=[
                f"原草图任务结果不可用（可能未完成或已过期）: {sketch_task_id}",
            ],
        )
        # 附加 metadata（虽然 schema 未定义，但 dict 形式可扩展）
        result_dict = result.model_dump(mode="json")
        result_dict["metadata"] = {
            "user_id": user_id,
            "sketch_task_id": sketch_task_id,
            "elapsed_ms": elapsed_ms,
            "error": "original_task_not_found",
        }
        return result_dict

    # 2. 提取 parse_result（兼容 SketchTaskResult.parse_result 字段）
    parse_result_dict = original_dict.get("parse_result") or {}
    try:
        parse_result = SketchParseResult.model_validate(parse_result_dict)
    except Exception as e:  # noqa: BLE001
        log.error(
            "sketch.calibration.parse_original_failed",
            task_id=task_id,
            error=str(e),
        )
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        result = CalibrationResult(
            task_id=task_id,
            success=False,
            calibrated_features=[],
            regenerated_code="",
            output_files={},
            warnings=[f"原解析结果反序列化失败: {e}"],
        )
        result_dict = result.model_dump(mode="json")
        result_dict["metadata"] = {
            "user_id": user_id,
            "sketch_task_id": sketch_task_id,
            "elapsed_ms": elapsed_ms,
            "error": "parse_result_invalid",
        }
        return result_dict

    # 3. 构造 CalibrationItem 列表
    try:
        calib_items = [CalibrationItem.model_validate(c) for c in calibrations]
    except Exception as e:  # noqa: BLE001
        log.error(
            "sketch.calibration.calibrations_invalid",
            task_id=task_id,
            error=str(e),
        )
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        result = CalibrationResult(
            task_id=task_id,
            success=False,
            calibrated_features=parse_result.features,
            regenerated_code="",
            output_files={},
            warnings=[f"校准项格式无效: {e}"],
        )
        result_dict = result.model_dump(mode="json")
        result_dict["metadata"] = {
            "user_id": user_id,
            "sketch_task_id": sketch_task_id,
            "elapsed_ms": elapsed_ms,
            "error": "calibrations_invalid",
        }
        return result_dict

    # 4. 校准 + 重新生成
    out_dir = _ensure_output_dir(f"{task_id}_calib")
    calib_result = calibrate_and_regenerate(
        parse_result=parse_result,
        calibrations=calib_items,
        output_dir=out_dir,
        output_format=output_format,
    )

    elapsed_ms = int((time.perf_counter() - t_start) * 1000)
    log.info(
        "sketch.calibration.done",
        task_id=task_id,
        success=calib_result.success,
        output_count=len(calib_result.output_files),
        elapsed_ms=elapsed_ms,
    )

    result_dict = calib_result.model_dump(mode="json")
    result_dict["metadata"] = {
        "user_id": user_id,
        "sketch_task_id": sketch_task_id,
        "calibrations_count": len(calib_items),
        "elapsed_ms": elapsed_ms,
        "original_task_success": original_dict.get("success"),
    }
    return result_dict


# ===== 离线自检 =====


def _self_test() -> dict[str, Any]:
    """离线自检：验证 Celery sketch 任务模块完整性。

    本函数不调用 VLM、不连接 Redis（除非显式 eager 调用），
    用于 CI / 离线环境验证模块可导入性与任务注册完整性。

    Returns:
        {"ok": bool, "errors": list[str], "checks": dict[str, bool]}
    """
    checks: dict[str, bool] = {}
    errors: list[str] = []

    # 1. 模块导入安全
    try:
        checks["module_import"] = True
        checks["parse_sketch_callable"] = callable(parse_sketch)
        checks["sketch_features_to_cadquery_callable"] = callable(
            sketch_features_to_cadquery
        )
        checks["sketch_to_dxf_via_cadquery_callable"] = callable(
            sketch_to_dxf_via_cadquery
        )
        checks["calibrate_and_regenerate_callable"] = callable(
            calibrate_and_regenerate
        )
    except Exception as e:  # noqa: BLE001
        checks["module_import"] = False
        errors.append(f"模块导入失败: {e}")

    # 2. Celery 任务已注册
    try:
        expected_task_names = {
            "app.celery.tasks.sketch.run_sketch_to_cad",
            "app.celery.tasks.sketch.run_sketch_calibration",
        }
        registered = set(celery_app.tasks.keys())
        missing = expected_task_names - registered
        checks["all_tasks_registered"] = len(missing) == 0
        if missing:
            errors.append(f"未注册的任务: {missing}")
    except Exception as e:  # noqa: BLE001
        checks["all_tasks_registered"] = False
        errors.append(f"任务注册校验失败: {e}")

    # 3. 任务可调用
    try:
        checks["run_sketch_to_cad_callable"] = callable(run_sketch_to_cad)
        checks["run_sketch_calibration_callable"] = callable(run_sketch_calibration)
    except Exception as e:  # noqa: BLE001
        checks["tasks_callable"] = False
        errors.append(f"任务可调用性校验失败: {e}")

    # 4. 任务配置合规
    try:
        checks["sketch_task_time_limit_300"] = (
            getattr(run_sketch_to_cad, "time_limit", None) == 300
        )
        checks["sketch_task_soft_time_limit_270"] = (
            getattr(run_sketch_to_cad, "soft_time_limit", None) == 270
        )
        checks["sketch_task_acks_late"] = (
            getattr(run_sketch_to_cad, "acks_late", False) is True
        )
        checks["calibration_task_time_limit_120"] = (
            getattr(run_sketch_calibration, "time_limit", None) == 120
        )
    except Exception as e:  # noqa: BLE001
        checks["task_config"] = False
        errors.append(f"任务配置校验失败: {e}")

    # 5. 工具函数可调用
    try:
        checks["resolve_image_path_callable"] = callable(_resolve_image_path)
        checks["ensure_output_dir_callable"] = callable(_ensure_output_dir)
        checks["fetch_sketch_parse_result_callable"] = callable(
            _fetch_sketch_parse_result
        )
        # 验证 _resolve_image_path 在文件不存在时返回有效路径对象
        p = _resolve_image_path("nonexistent_test_image.png")
        checks["resolve_image_path_returns_path"] = isinstance(p, Path)
    except Exception as e:  # noqa: BLE001
        checks["util_functions"] = False
        errors.append(f"工具函数校验失败: {e}")

    # 6. 草图特征 → 任务结果 schema 一致性
    try:
        # 构造空 parse_result 验证 SketchTaskResult schema
        empty_parse = SketchParseResult(warnings=["test"])
        empty_result = SketchTaskResult(
            task_id="test",
            success=False,
            precision_level="sketch_level",
            parse_result=empty_parse,
        )
        checks["sketch_task_result_schema_ok"] = (
            empty_result.precision_level == "sketch_level"
            and empty_result.task_id == "test"
        )
        # 验证 CalibrationItem schema
        c = CalibrationItem(
            feature_index=0,
            feature_type="circle",
            parameter_name="radius",
            calibrated_value=50.0,
        )
        checks["calibration_item_schema_ok"] = (
            c.feature_index == 0 and c.unit == "mm"
        )
    except Exception as e:  # noqa: BLE001
        checks["schema_validation"] = False
        errors.append(f"schema 校验失败: {e}")

    ok = all(checks.values()) if checks else False
    return {"ok": ok, "errors": errors, "checks": checks}


__all__ = [
    "run_sketch_to_cad",
    "run_sketch_calibration",
    "_self_test",
]


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys

    result = _self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["ok"] else 1)
