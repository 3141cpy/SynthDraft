"""装配生成 Celery 任务（Task 10.5）。

编排流程：
1. run_assembly_generation：装配体生成主任务
    - 输入：AssemblySpec（LLM 生成或用户构造）
    - 验证：调用 validator.validate_assembly
    - 生成：为每个零件生成 STEP/SLDPRT（standard_parts 工厂 → CadQuery 沙箱）
    - 装配：计算 mate 变换，输出 SLDASM（Windows）或 STEP 装配体（Linux 降级）
    - 导出：BOM（CSV/JSON）+ 装配图（DXF）
    - 返回：AssemblyGenerationResult

跨平台策略（"以瞎猜接口为耻"）：
- SolidWorks 不可用时降级为 STEP 装配体（每个零件 STEP + 装配 STEP）
- CadQuery 沙箱不可用时仅返回验证报告 + BOM + DXF（无 3D 实体）
- 所有降级路径在 warnings 中明确标注

队列：generations（Linux AI 服务消费；SolidWorks 子任务路由到 solidworks 队列）
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
from app.schemas.assembly import (
    AssemblyGenerationResult,
    AssemblySpec,
    AssemblyValidationReport,
)
from app.utils.path_safety import resolve_within_roots

log = get_logger(__name__)

# 上传根目录（用于 step_file 路径校验）
_LOCAL_UPLOAD_DIR = Path(settings.UPLOAD_DIR).resolve()

# step_file 查找允许的根目录（上传目录 + 开发态 fixtures）
_STEP_FILE_ROOTS: list[Path] = [
    _LOCAL_UPLOAD_DIR,
    Path("./tests/fixtures").resolve(),
]


@celery_app.task(
    name="app.celery.tasks.assembly.run_assembly_generation",
    bind=True,
    base=BaseTask,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=2,
    acks_late=True,
    time_limit=600,        # 硬超时 10 分钟（装配体生成较慢）
    soft_time_limit=540,   # 软超时 9 分钟
)
def run_assembly_generation(
    self: BaseTask,
    spec_dict: dict[str, Any],
    output_dir: str | None = None,
    generate_sldasm: bool = True,
    generate_bom: bool = True,
    generate_drawing: bool = True,
) -> dict[str, Any]:
    """装配体生成主任务。

    Args:
        spec_dict: AssemblySpec 序列化 dict
        output_dir: 输出目录（None 时使用临时目录）
        generate_sldasm: 是否生成 SLDASM/STEP 装配体
        generate_bom: 是否导出 BOM
        generate_drawing: 是否导出装配图

    Returns:
        AssemblyGenerationResult dict
    """
    task_id = self.request.id or f"asm-{uuid.uuid4().hex[:8]}"
    t_start = time.perf_counter()
    log.info(
        "assembly.generation.start",
        task_id=task_id,
        name=spec_dict.get("name", "unknown"),
        parts=len(spec_dict.get("parts", [])),
        mates=len(spec_dict.get("mates", [])),
    )

    warnings: list[str] = []
    output_files: dict[str, str] = {}
    bom_items: list[dict[str, Any]] = []
    validation_report: AssemblyValidationReport | None = None

    try:
        spec = AssemblySpec(**spec_dict)
    except Exception as e:  # noqa: BLE001
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        return AssemblyGenerationResult(
            task_id=task_id,
            assembly_name=spec_dict.get("name", "unknown"),
            success=False,
            elapsed_ms=elapsed_ms,
            error=f"AssemblySpec 解析失败: {e}",
            warnings=warnings,
        ).model_dump(mode="json")

    # 输出目录
    if output_dir is None:
        output_dir = f"./tmp_uploads/assembly_{task_id}"
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    try:
        # 1. 验证装配规范
        from app.services.assembly.validator import validate_assembly
        validation_report = validate_assembly(spec)
        if not validation_report.is_valid:
            warnings.append(
                f"装配验证未通过（passed={validation_report.passed_count}/5），"
                "继续生成但建议人工复核"
            )

        # 2. 为每个零件生成 STEP（通过 CadQuery 沙箱）
        if generate_sldasm:
            try:
                part_files = _generate_all_parts(spec, out_path, warnings)
                output_files.update(part_files)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"零件 3D 生成失败: {e}")

            # 3. 生成装配体（SLDASM 或 STEP 降级）
            try:
                asm_file = _generate_assembly(spec, out_path, warnings)
                if asm_file is not None:
                    output_files["assembly"] = str(asm_file)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"装配体生成失败: {e}")

        # 4. 导出 BOM
        if generate_bom:
            try:
                from app.services.assembly.bom_exporter import export_bom
                bom_csv = export_bom(spec, out_path / "bom.csv", "csv")
                bom_json = export_bom(spec, out_path / "bom.json", "json")
                output_files["bom_csv"] = str(bom_csv)
                output_files["bom_json"] = str(bom_json)
                bom_items = _build_bom_summary(spec)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"BOM 导出失败: {e}")

        # 5. 导出装配图
        if generate_drawing:
            try:
                from app.services.assembly.bom_exporter import (
                    export_assembly_drawing,
                )
                dxf_path = export_assembly_drawing(
                    spec, out_path / "assembly.dxf", "A3",
                )
                output_files["drawing_dxf"] = str(dxf_path)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"装配图导出失败: {e}")

        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        result = AssemblyGenerationResult(
            task_id=task_id,
            assembly_name=spec.name,
            success=True,
            validation_report=validation_report,
            output_files=output_files,
            bom_items=bom_items,
            elapsed_ms=elapsed_ms,
            warnings=warnings,
            metadata={
                "parts_count": len(spec.parts),
                "mates_count": len(spec.mates),
                "axioms_count": len(spec.axioms),
            },
        )
        log.info(
            "assembly.generation.done",
            task_id=task_id,
            success=True,
            elapsed_ms=elapsed_ms,
            output_count=len(output_files),
        )
        return result.model_dump(mode="json")
    except Exception as e:  # noqa: BLE001
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.error(
            "assembly.generation.failed",
            task_id=task_id,
            error=str(e),
            elapsed_ms=elapsed_ms,
        )
        return AssemblyGenerationResult(
            task_id=task_id,
            assembly_name=spec.name,
            success=False,
            elapsed_ms=elapsed_ms,
            error=str(e),
            warnings=warnings,
            validation_report=validation_report,
        ).model_dump(mode="json")


# ===== 辅助：零件 3D 生成 =====


def _generate_all_parts(
    spec: AssemblySpec,
    out_path: Path,
    warnings: list[str],
) -> dict[str, str]:
    """为每个零件生成 STEP 文件。

    策略：
    - generator=standard_part：调用 CadQuery 沙箱
    - generator=cadquery_code：直接执行 CadQuery 代码
    - generator=step_file：直接复制引用的 STEP 文件
    - generator=features：跳过（需 SolidWorks 才能生成）
    """
    from app.services.assembly.standard_parts import create_part

    part_files: dict[str, str] = {}
    for part in spec.parts:
        try:
            step_path = out_path / f"{part.part_id}.step"
            if part.generator == "step_file" and part.step_file:
                # 直接复制引用的 STEP（校验路径归属，防穿越 - Part 3）
                import shutil
                try:
                    src = resolve_within_roots(part.step_file, _STEP_FILE_ROOTS)
                except (FileNotFoundError, ValueError) as e:
                    warnings.append(
                        f"零件 {part.part_id} step_file 路径非法或不存在: {e}"
                    )
                    continue
                shutil.copy2(src, step_path)
                part_files[part.part_id] = str(step_path)
                part.generated_file = str(step_path)
                continue

            if part.generator in ("standard_part", "cadquery_code"):
                code = part.cadquery_code
                if not code:
                    warnings.append(
                        f"零件 {part.part_id} 无 cadquery_code，跳过生成"
                    )
                    continue
                # 调用 CadQuery 沙箱
                step_path = _run_cadquery_to_step(
                    code, step_path, part.part_id, warnings,
                )
                if step_path is not None:
                    part_files[part.part_id] = str(step_path)
                    part.generated_file = str(step_path)
                continue

            if part.generator == "features":
                warnings.append(
                    f"零件 {part.part_id} generator=features 需要 SolidWorks，"
                    "本环境跳过"
                )
                continue

            warnings.append(
                f"零件 {part.part_id} 未知 generator: {part.generator}"
            )
        except Exception as e:  # noqa: BLE001
            warnings.append(f"零件 {part.part_id} 生成失败: {e}")

    return part_files


def _run_cadquery_to_step(
    code: str,
    output_path: Path,
    part_id: str,
    warnings: list[str],
) -> Path | None:
    """在 CadQuery 沙箱中执行代码生成 STEP。

    复用 generation/sandbox.py 的执行器。为每个零件创建隔离子目录，
    避免 ``glob("*.step")`` 非确定性返回前序 part 的文件（Finding 11）。
    """
    import shutil

    try:
        from app.services.generation.sandbox import execute_cadquery_code
    except ImportError:
        warnings.append("CadQuery 沙箱不可用（generation.sandbox 导入失败）")
        return None

    # 隔离工作目录，避免多 part 共享输出目录导致 STEP 污染（Finding 11）
    work_dir = output_path.parent / f"_{part_id}_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = execute_cadquery_code(
            code=code,
            output_dir=work_dir,
            timeout=60,
            output_format="step",
        )
        if not result.success:
            warnings.append(
                f"零件 {part_id} CadQuery 执行失败: "
                f"stderr={result.stderr[:200] if result.stderr else 'unknown'}"
            )
            return None
        # 查找生成的 STEP（仅在隔离子目录内查找）
        step_files = list(work_dir.glob("*.step")) + list(
            work_dir.glob("*.stp")
        )
        if not step_files:
            warnings.append(
                f"零件 {part_id} CadQuery 执行成功但未生成 STEP"
            )
            return None
        # 复制到目标路径
        src = step_files[0]
        shutil.copy2(src, output_path)
        return output_path
    except Exception as e:  # noqa: BLE001
        warnings.append(f"零件 {part_id} CadQuery 沙箱异常: {e}")
        return None
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _generate_assembly(
    spec: AssemblySpec,
    out_path: Path,
    warnings: list[str],
) -> Path | None:
    """生成装配体文件。

    策略：
    - Windows + SolidWorks 可用：调用 writer.generate_sldasm_from_components
    - 否则：尝试 STEP 装配体（通过 CadQuery assembly 或 pythonOCC）
    - 都不可用：跳过（仅保留 BOM/DXF 输出）
    """
    # 收集已生成的零件 STEP 文件
    part_steps: dict[str, Path] = {}
    for part in spec.parts:
        if part.generated_file:
            p = Path(part.generated_file)
            if p.is_file():
                part_steps[part.part_id] = p

    if not part_steps:
        warnings.append("无可用零件 STEP，跳过装配体生成")
        return None

    # 尝试 SolidWorks 路径
    try:
        from app.services.solidworks.sw_session import is_solidworks_available
        if is_solidworks_available():
            return _generate_via_solidworks(spec, out_path, part_steps, warnings)
    except ImportError:
        pass

    # 降级：STEP 装配体（pythonOCC）
    return _generate_step_assembly(spec, out_path, part_steps, warnings)


def _generate_via_solidworks(
    spec: AssemblySpec,
    out_path: Path,
    part_steps: dict[str, Path],
    warnings: list[str],
) -> Path | None:
    """通过 SolidWorks API 生成 SLDASM。"""
    try:
        from app.schemas.solidworks_model import SWComponent, SWMate
        from app.services.solidworks.writer import generate_sldasm_from_components
        from app.services.assembly.mate_library import apply_mate_transforms
    except ImportError as e:
        warnings.append(f"SolidWorks writer 不可用: {e}")
        return None

    # 构造 SWComponent 列表
    transforms, mate_warnings = apply_mate_transforms(spec.parts, spec.mates)
    warnings.extend(mate_warnings)

    components: list[SWComponent] = []
    for part in spec.parts:
        if part.part_id not in part_steps:
            continue
        components.append(SWComponent(
            name=part.name,
            source_file=str(part_steps[part.part_id]),
            configuration=None,
            transform=transforms.get(part.part_id),
        ))

    sldasm_path = out_path / f"{spec.name}.SLDASM"
    try:
        result_path = generate_sldasm_from_components(
            components=components,
            output_path=sldasm_path,
            mates=[],  # 简化：仅定位，不添加 Mate 约束
        )
        return Path(result_path)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"SolidWorks SLDASM 生成失败: {e}")
        return None


def _generate_step_assembly(
    spec: AssemblySpec,
    out_path: Path,
    part_steps: dict[str, Path],
    warnings: list[str],
) -> Path | None:
    """通过 pythonOCC 或 CadQuery Assembly 生成 STEP 装配体。"""
    try:
        import cadquery as cq
    except ImportError:
        warnings.append("CadQuery 不可用，无法生成 STEP 装配体")
        return None

    try:
        from app.services.assembly.mate_library import (
            apply_mate_transforms, _list_to_mat,
        )
        import numpy as np
    except ImportError as e:
        warnings.append(f"装配库不可用: {e}")
        return None

    transforms, mate_warnings = apply_mate_transforms(spec.parts, spec.mates)
    warnings.extend(mate_warnings)

    assembly = cq.Assembly()
    for part in spec.parts:
        if part.part_id not in part_steps:
            continue
        try:
            shape = cq.importers.importStep(str(part_steps[part.part_id]))
        except Exception as e:  # noqa: BLE001
            warnings.append(
                f"零件 {part.part_id} STEP 导入失败: {e}"
            )
            continue
        # 应用变换矩阵
        t_list = transforms.get(part.part_id)
        if t_list:
            t_mat = _list_to_mat(t_list)
            # CadQuery 的 Location 接受 4×4 矩阵（行主序 numpy 数组）
            loc = cq.Location(cq.Matrix(t_mat.tolist()))
            assembly.add(shape, name=part.part_id, loc=loc)
        else:
            assembly.add(shape, name=part.part_id)

    step_path = out_path / f"{spec.name}.step"
    try:
        assembly.save(str(step_path))
        return step_path
    except Exception as e:  # noqa: BLE001
        warnings.append(f"STEP 装配体保存失败: {e}")
        return None


def _build_bom_summary(spec: AssemblySpec) -> list[dict[str, Any]]:
    """构造 BOM 摘要（用于任务返回）。"""
    from app.services.assembly.bom_exporter import _build_bom_items
    return _build_bom_items(spec)


# ===== 模块自检 =====


def _self_test() -> dict[str, Any]:
    """离线自检：验证任务注册与可调用性。"""
    checks: dict[str, bool] = {}
    try:
        from app.celery.tasks.assembly import run_assembly_generation  # noqa: F401
        checks["task_import"] = True
    except Exception:
        checks["task_import"] = False
    # 任务已注册到 celery_app
    task_name = "app.celery.tasks.assembly.run_assembly_generation"
    checks["task_registered"] = task_name in celery_app.tasks
    # 可调用
    checks["task_callable"] = callable(run_assembly_generation)
    ok = all(checks.values())
    return {"ok": ok, "checks": checks}


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys
    result = _self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["ok"] else 1)
