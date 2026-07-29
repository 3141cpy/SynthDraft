"""生成任务（Task 5）。

完整管线：
1. ``generate_cadquery_code`` 或 ``template_match_generate`` 生成代码
2. ``static_scan_code`` + ``execute_cadquery_code``（沙箱执行）
3. ``validate_step_file``（几何校验）
4. 异步派发 ``reviews.run_review`` 进行自检（不阻断主流程，结果记入 metadata）
5. 返回 ``GenerationResult`` dict

降级策略：
- LLM 不可用 → 模板匹配（mode=template）
- 沙箱执行失败（LLM 幻觉 API 等导致 success=False 或无产出文件）
  → 自动降级到 ``template_match_generate`` 重新生成并重新执行
  → 保证协同闭环（审图→生成→复审）能产出真实文件
- 几何校验失败 → geometry_validation.errors 非空，is_valid=False
- 审图自检派发失败 → 仅记录 metadata.self_review_error，不影响生成结果
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from app.celery.base import BaseTask
from app.celery.tasks.reviews import run_review
from app.celery_app import celery_app
from app.config import settings
from app.logging import get_logger
from app.schemas.generation_detail import (
    ExecutionResult,
    GeometryValidation,
    GenerationResult,
)
from app.services.generation import (
    execute_cadquery_code,
    generate_cadquery_code,
    is_llm_available,
    template_match_generate,
    validate_step_file,
)

log = get_logger(__name__)


def generate_and_execute_with_fallback(
    prompt: str,
    out_dir: Path,
    fmt: str,
    task_id: str = "unknown",
    timeout: int = 30,
) -> tuple[str, str, ExecutionResult, int]:
    """生成 CadQuery 代码并沙箱执行；沙箱失败时降级到 template 重试。

    协同闭环（审图→生成→复审）的关键修复点：LLM 可能生成语法合法但
    语义错误的"幻觉 API"代码（如 ``.edges("|@10mm").dim(...)``），
    ``_is_valid_llm_code`` 仅做语法校验无法拦截，导致沙箱执行失败
    （exit_code=1, files=[]）。本函数在沙箱失败时自动降级到
    ``template_match_generate`` 重新生成代码并重新执行，保证最终
    产出真实文件。

    Args:
        prompt: 自然语言零件描述
        out_dir: 沙箱输出目录（不存在则创建）
        fmt: 输出格式（step/stl/dxf/iges）
        task_id: 任务 ID（用于日志）
        timeout: 沙箱执行超时秒数

    Returns:
        (code, mode, execution, gen_elapsed_ms) 四元组：
        - code: 最终生效的 CadQuery 代码（可能是 LLM 或 template）
        - mode: "llm" 或 "template"（降级后为 "template"）
        - execution: 最终沙箱执行结果（降级重试后的）
        - gen_elapsed_ms: 代码生成耗时（毫秒，不含沙箱执行）
    """
    t0 = time.time()
    try:
        if is_llm_available() and prompt:
            code, mode = generate_cadquery_code(prompt)
        else:
            code = template_match_generate(prompt or "立方体 10mm")
            mode = "template"
    except Exception as e:  # noqa: BLE001
        log.warning("generation.codegen.failed, fallback to template", error=str(e))
        code = template_match_generate(prompt or "立方体 10mm")
        mode = "template"
    gen_elapsed_ms = int((time.time() - t0) * 1000)
    log.info(
        "generation.codegen.done",
        task_id=task_id,
        mode=mode,
        code_len=len(code),
        elapsed_ms=gen_elapsed_ms,
    )

    execution = execute_cadquery_code(
        code=code,
        output_dir=out_dir,
        timeout=timeout,
        output_format=fmt,
    )
    log.info(
        "generation.execute.done",
        task_id=task_id,
        success=execution.success,
        output_count=len(execution.output_files),
        elapsed_ms=execution.elapsed_ms,
    )

    # ===== 沙箱执行失败降级（协同闭环修复）=====
    # LLM 生成代码可能含幻觉 API（语法合法但语义错误），
    # 沙箱执行会捕获运行时异常并以 exit_code=1 退出。
    # 此时降级到 template_match_generate 重新生成 + 重新执行，
    # 保证协同闭环产出真实文件。
    if mode == "llm" and (not execution.success or not execution.output_files):
        log.warning(
            "collaboration.sandbox_failed_fallback_to_template",
            task_id=task_id,
            exit_code=execution.exit_code,
            output_count=len(execution.output_files),
            stderr_tail=(execution.stderr or "")[-300:],
        )
        # 使用独立的 fallback 目录，避免失败执行的残留文件干扰
        fallback_dir = out_dir.parent / f"{out_dir.name}_fallback"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        code = template_match_generate(prompt or "立方体 10mm")
        mode = "template"
        execution = execute_cadquery_code(
            code=code,
            output_dir=fallback_dir,
            timeout=timeout,
            output_format=fmt,
        )
        log.info(
            "generation.execute.fallback_done",
            task_id=task_id,
            success=execution.success,
            output_count=len(execution.output_files),
            elapsed_ms=execution.elapsed_ms,
            mode=mode,
        )

    return code, mode, execution, gen_elapsed_ms


@celery_app.task(
    name="app.celery.tasks.generations.run_generation",
    bind=True,
    base=BaseTask,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
    time_limit=180,        # 硬超时 3 分钟
    soft_time_limit=150,   # 软超时 2.5 分钟
)
def run_generation(
    self: BaseTask,
    input_type: str,
    prompt: str | None,
    sketch_key: str | None,
    output_format: str,
    user_id: str = "anonymous",
) -> dict[str, Any]:
    """生成任务入口（完整管线）。

    Args:
        input_type: 输入类型（text/sketch）
        prompt: 自然语言描述
        sketch_key: 草图对象 key（sketch 模式）
        output_format: 期望输出格式（step/stl/dxf/iges）
        user_id: 提交用户 ID

    Returns:
        GenerationResult dict（与 schema 一致）
    """
    task_id = self.request.id or "unknown"
    log.info(
        "generation.task.start",
        task_id=task_id,
        input_type=input_type,
        output_format=output_format,
        user=user_id,
    )

    effective_prompt = prompt or ""
    if input_type == "sketch" and not effective_prompt:
        effective_prompt = "草图转 CAD（基于 sketch_key）"

    # ===== 1 + 2. 生成 CadQuery 代码 + 沙箱执行（含失败降级）=====
    # 协同闭环修复：LLM 幻觉 API 导致沙箱执行失败时，自动降级到
    # template_match_generate 重新生成并重新执行，保证产出真实文件。
    # 详见 generate_and_execute_with_fallback() 文档。
    run_id = uuid.uuid4().hex[:12]
    out_root = Path(settings.UPLOAD_DIR).resolve() / "generations"
    out_root.mkdir(parents=True, exist_ok=True)
    out_dir = out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # 限制输出格式到合法集合
    fmt = output_format.lower() if output_format else "step"
    if fmt not in ("step", "stl", "dxf", "iges"):
        fmt = "step"

    code, mode, execution, gen_elapsed_ms = generate_and_execute_with_fallback(
        prompt=effective_prompt,
        out_dir=out_dir,
        fmt=fmt,
        task_id=task_id,
        timeout=30,
    )

    # ===== 3. 几何校验（仅 STEP 文件存在时） =====
    geo_val: GeometryValidation | None = None
    step_files = [
        p for p in execution.output_files
        if p.lower().endswith((".step", ".stp"))
    ]
    if step_files:
        geo_val = validate_step_file(Path(step_files[0]))

    # ===== 4. 自动派发审图自检（异步，不阻断主流程） =====
    # 派发条件：
    #   - 输出格式为 dxf（reviews.prepare_review_context 当前仅支持 DXF；
    #     STEP/STL/IGES 等 3D 格式审图支持属于 P1 Task 9 范围）
    #   - 几何校验通过（避免对失败产物做无意义审图）
    # run_review 在独立 celery 队列执行，失败由其自身 autoretry 处理，
    # generations 主流程仅记录派发信息。
    self_review_task_id: str | None = None
    self_review_status: str = "skipped"  # skipped / skipped_unsupported / dispatched / dispatch_failed
    self_review_error: str | None = None
    # 当前 reviews 支持的文件类型集合（与 pipeline.prepare_review_context 对齐）
    _REVIEW_SUPPORTED_FORMATS = {"dxf"}
    # 找到首个 reviews 支持的输出文件作为自检输入
    self_review_file: str | None = None
    if geo_val is not None and geo_val.is_valid:
        for p in execution.output_files:
            ext = Path(p).suffix.lstrip(".").lower()
            if ext in _REVIEW_SUPPORTED_FORMATS:
                self_review_file = p
                break
        if self_review_file is None:
            self_review_status = "skipped_unsupported"
            self_review_error = (
                f"output_format={fmt}; reviews pipeline supports only "
                f"{sorted(_REVIEW_SUPPORTED_FORMATS)} in P0"
            )
        else:
            try:
                async_result = run_review.apply_async(
                    args=[
                        self_review_file,          # file_key: 文件绝对路径
                        "dxf",                     # file_type
                        ["GB/T 18229-2023"],       # standard_set: CAD 工程制图通用规范
                        user_id,                   # user_id 透传
                    ]
                )
                self_review_task_id = async_result.id
                self_review_status = "dispatched"
                log.info(
                    "generation.self_review.dispatched",
                    task_id=task_id,
                    self_review_task_id=self_review_task_id,
                    file_key=self_review_file,
                )
            except Exception as e:  # noqa: BLE001
                # 派发失败（broker 不可达 / 序列化失败等）不阻断主流程
                self_review_error = str(e)
                self_review_status = "dispatch_failed"
                log.warning(
                    "generation.self_review.dispatch_failed",
                    task_id=task_id,
                    error=self_review_error,
                )

    # ===== 5. 组装结果 =====
    result = GenerationResult(
        task_id=task_id,
        input_prompt=effective_prompt,
        generated_code=code,
        execution=execution,
        geometry_validation=geo_val,
        output_files=execution.output_files,
        mode=mode,  # type: ignore[arg-type]
        metadata={
            "user_id": user_id,
            "input_type": input_type,
            "sketch_key": sketch_key,
            "output_format": fmt,
            "codegen_elapsed_ms": gen_elapsed_ms,
            "llm_available": is_llm_available(),
            "llm_model": settings.LLM_MODEL if is_llm_available() else None,
            "run_id": run_id,
            "self_review_task_id": self_review_task_id,
            "self_review_status": self_review_status,
            "self_review_error": self_review_error,
            "self_review_standard_set": ["GB/T 18229-2023"]
            if self_review_status == "dispatched"
            else None,
        },
    )

    log.info(
        "generation.task.done",
        task_id=task_id,
        success=execution.success,
        geo_valid=geo_val.is_valid if geo_val else None,
        volume=geo_val.volume if geo_val else None,
        mode=mode,
        self_review_status=self_review_status,
        self_review_task_id=self_review_task_id,
    )
    return result.model_dump(mode="json")
