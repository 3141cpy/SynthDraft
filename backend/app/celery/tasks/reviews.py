"""审图任务（Task 4 真实管线）。

管线：
1) 从 MinIO/本地下载文件（P0 降级为本地 tmp 目录）
2) prepare_review_context()：DXF 解析 + 图片渲染
3) VLM OCR（可用时）+ fuse_to_semantic_model()：三层语义融合
4) retrieve_relevant_clauses() + llm_judge_defects()（或 rule_engine_judge 降级）
5) compute_compliance_score()
6) generate_html_report() + generate_pdf_report()
7) 上传报告到 MinIO（P0 降级为本地 reports/ 目录）
8) 返回 ReviewResult（dict 形式，可被 Celery JSON 序列化）
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from app.celery.base import BaseTask
from app.celery_app import celery_app
from app.logging import get_logger
from app.schemas.review_detail import ReviewResult
from app.services.review.llm_judge import is_llm_available, judge_with_fallback
from app.services.review.pipeline import fuse_to_semantic_model, prepare_review_context
from app.services.review.report import generate_html_report, generate_pdf_report
from app.services.review.scoring import compute_compliance_score
from app.services.review.vlm_ocr import is_vlm_available, vlm_detect_regions, vlm_ocr_extract
from app.utils.path_safety import resolve_within_roots

log = get_logger(__name__)

# P0 本地存储目录（相对 worker cwd）
_LOCAL_UPLOAD_DIR = Path("./tmp_uploads")

# 文件查找允许的根目录（上传目录 + 开发态 fixtures）
_FILE_ROOTS: list[Path] = [
    _LOCAL_UPLOAD_DIR.resolve(),
    Path("./tests/fixtures").resolve(),
]


@celery_app.task(
    name="app.celery.tasks.reviews.run_review",
    bind=True,
    base=BaseTask,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
    time_limit=600,        # 硬超时 10 分钟（LLM 推理可能较慢）
    soft_time_limit=540,   # 软超时 9 分钟
)
def run_review(
    self: BaseTask,
    file_key: str,
    file_type: str,
    standard_set: list[str],
    user_id: str = "anonymous",
) -> dict[str, Any]:
    """审图任务入口。

    Args:
        file_key: MinIO 中已上传文件的 key，或本地相对路径（P0）
        file_type: 输入文件类型（sldprt/sldasm/dwg/dxf/pdf/image）
        standard_set: 适用的规范集合
        user_id: 提交用户 ID

    Returns:
        dict 形式的 ReviewResult（可被 Celery JSON 序列化）
    """
    task_id = self.request.id
    t_start = time.perf_counter()
    log.info(
        "review.task.start",
        task_id=task_id,
        file_key=file_key,
        file_type=file_type,
        standards=standard_set,
        user=user_id,
    )

    # ===== 步骤 1：解析文件路径（P0 降级：本地 tmp_uploads/）=====
    dxf_path = _resolve_file_path(file_key)
    if not dxf_path.is_file():
        raise FileNotFoundError(f"审图文件不存在: {dxf_path}")

    # ===== 步骤 2：prepare_review_context =====
    log.info("review.task.prepare_context", task_id=task_id, path=str(dxf_path))
    ctx = prepare_review_context(dxf_path)

    # ===== 步骤 3：VLM OCR + 语义融合 =====
    vlm_result: dict[str, Any] = {}
    vlm_available = is_vlm_available()
    if vlm_available and ctx.image_path:
        log.info("review.task.vlm_detect", task_id=task_id)
        regions = vlm_detect_regions(Path(ctx.image_path))
        vlm_result = vlm_ocr_extract(Path(ctx.image_path), regions)
    else:
        log.info(
            "review.task.vlm_skipped",
            task_id=task_id,
            vlm_available=vlm_available,
            has_image=ctx.image_path is not None,
        )

    semantic_model = fuse_to_semantic_model(ctx.cad_model, vlm_result)

    # ===== 步骤 4：检索 + 判定 =====
    log.info("review.task.judge", task_id=task_id, llm_available=is_llm_available())
    defects, judge_mode, llm_model = judge_with_fallback(
        semantic_model, use_llm=True, top_k=5
    )

    # 综合审图模式：vlm / vector_only / rule_engine
    if judge_mode == "llm":
        review_mode = "vlm" if vlm_available and vlm_result else "vector_only"
    else:
        review_mode = "rule_engine"

    # ===== 步骤 5：评分 =====
    score = compute_compliance_score(defects)

    # ===== 步骤 6：生成报告 =====
    metadata: dict[str, Any] = {
        "image_path": ctx.image_path,
        "parse_metadata": ctx.parse_metadata,
        "judge_mode": judge_mode,
        "llm_model": llm_model,
        "vlm_available": vlm_available,
        "vlm_result_keys": list(vlm_result.keys()) if vlm_result else [],
        "entity_count": len(ctx.cad_model.entities),
        "dimension_count": len(ctx.cad_model.dimensions),
        "elapsed_ms": 0,  # 后填
    }

    # 构造 ReviewResult（先无 report_path）
    result = ReviewResult(
        task_id=task_id,
        file_key=file_key,
        file_type=file_type,
        status="completed",
        compliance_score=score,
        defects=defects,
        standards_applied=standard_set,
        review_mode=review_mode,  # type: ignore[arg-type]
        report_path=None,
        pdf_report_path=None,
        metadata=metadata,
    )

    log.info("review.task.generate_report", task_id=task_id, mode=review_mode)
    try:
        html_path = generate_html_report(result)
        result.report_path = str(html_path)
        pdf_path = generate_pdf_report(html_path)
        if pdf_path is not None:
            result.pdf_report_path = str(pdf_path)
    except Exception as e:  # noqa: BLE001
        log.error("review.task.report_failed", task_id=task_id, error=str(e))

    elapsed_ms = int((time.perf_counter() - t_start) * 1000)
    result.metadata["elapsed_ms"] = elapsed_ms

    log.info(
        "review.task.done",
        task_id=task_id,
        score=score,
        defects_count=len(defects),
        review_mode=review_mode,
        elapsed_ms=elapsed_ms,
        report_path=result.report_path,
    )

    # 返回 dict（Celery JSON 序列化）
    return result.model_dump(mode="json")


def _resolve_file_path(file_key: str) -> Path:
    """解析 file_key 为本地文件路径。

    使用 resolve_within_roots 在允许根目录内查找，拒绝绝对路径与穿越攻击
    （Finding 8）。文件未找到或路径非法时返回安全占位路径（仅取文件名，
    无穿越风险），由调用方 ``is_file()`` 检查处理。
    """
    try:
        return resolve_within_roots(file_key, _FILE_ROOTS)
    except (FileNotFoundError, ValueError):
        return _LOCAL_UPLOAD_DIR / Path(file_key).name
