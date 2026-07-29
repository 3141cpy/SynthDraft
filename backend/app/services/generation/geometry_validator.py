"""执行结果几何校验（SubTask 5.3）。

调用 Task 2 的 ``app.services.cad.occ_engine`` 校验生成的 STEP 文件：
- 体积 > 0
- 包围盒在合理范围（< 10000mm 各向）
- 表面积 > 0
- 自相交检测（若 OCP 支持）

依赖：
- ``app.services.cad.occ_engine.read_step_file``
- ``app.services.cad.occ_engine.get_bounding_box``
- ``app.services.cad.occ_engine.get_volume``
- ``app.services.cad.occ_engine.get_surface_area``
"""

from __future__ import annotations

from pathlib import Path

from app.logging import get_logger
from app.schemas.generation_detail import GeometryValidation
from app.services.cad.occ_engine import (
    OCCEngineNotAvailableError,
    get_bounding_box,
    get_surface_area,
    get_volume,
    is_occ_available,
    read_step_file,
)

__all__ = ["validate_step_file"]

log = get_logger(__name__)

# 包围盒各向最大尺寸（mm），超过视为不合理
_MAX_BBOX_DIM = 10000.0


def validate_step_file(step_path: Path) -> GeometryValidation:
    """校验 STEP 文件的几何合法性。

    Args:
        step_path: STEP 文件路径

    Returns:
        GeometryValidation 结构化校验结果

    Note:
        OCC 不可用时返回 is_valid=False 且 errors 含原因；
        文件读取失败时同样返回 is_valid=False。
    """
    path = Path(step_path)
    if not path.is_file():
        return GeometryValidation(
            is_valid=False,
            errors=[f"STEP 文件不存在: {path}"],
            backend=None,
        )

    if not is_occ_available():
        return GeometryValidation(
            is_valid=False,
            errors=["OCC 引擎不可用，无法做几何校验"],
            backend=None,
        )

    errors: list[str] = []
    volume = 0.0
    surface_area = 0.0
    bbox: tuple[float, float, float, float, float, float] | None = None
    backend = "OCP"  # occ_engine 实际后端，读 step 后会暴露

    try:
        read_result = read_step_file(path)
        shape = read_result["shape"]
        backend = read_result.get("backend", "OCP")
    except FileNotFoundError as e:
        return GeometryValidation(
            is_valid=False,
            errors=[f"STEP 文件不存在: {e}"],
            backend=None,
        )
    except Exception as e:  # noqa: BLE001
        return GeometryValidation(
            is_valid=False,
            errors=[f"STEP 读取失败: {type(e).__name__}: {e}"],
            backend=backend,
        )

    # 体积
    try:
        volume = get_volume(shape)
        if volume <= 0:
            errors.append(f"体积非正: {volume}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"体积计算失败: {type(e).__name__}: {e}")

    # 表面积
    try:
        surface_area = get_surface_area(shape)
        if surface_area <= 0:
            errors.append(f"表面积非正: {surface_area}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"表面积计算失败: {type(e).__name__}: {e}")

    # 包围盒
    try:
        bbox = get_bounding_box(shape)
        xmin, ymin, zmin, xmax, ymax, zmax = bbox
        dx = xmax - xmin
        dy = ymax - ymin
        dz = zmax - zmin
        for axis, dim in (("x", dx), ("y", dy), ("z", dz)):
            if dim <= 0:
                errors.append(f"包围盒 {axis} 方向尺寸非正: {dim}")
            if dim > _MAX_BBOX_DIM:
                errors.append(
                    f"包围盒 {axis} 方向尺寸超限: {dim} > {_MAX_BBOX_DIM}"
                )
    except Exception as e:  # noqa: BLE001
        errors.append(f"包围盒计算失败: {type(e).__name__}: {e}")

    # 自相交检测：OCP 提供 BRepAlgoAPI_Check，P0 阶段保守跳过（性能考量）
    # 若后续需要可在此扩展：from OCP.BRepAlgoAPI import BRepAlgoAPI_Check
    # P0 仅在体积/表面积/包围盒都正常时返回 is_valid=True

    is_valid = len(errors) == 0 and volume > 0
    log.info(
        "geometry.validate.done",
        file=str(path),
        is_valid=is_valid,
        volume=volume,
        surface_area=surface_area,
        bbox=bbox,
        errors=errors,
    )

    return GeometryValidation(
        is_valid=is_valid,
        volume=volume,
        bounding_box=bbox,
        surface_area=surface_area,
        errors=errors,
        backend=backend,
    )
