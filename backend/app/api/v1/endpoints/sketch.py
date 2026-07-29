"""草图转 CAD 端点（Task 12）。

端点：
- POST /api/v1/sketches
    提交草图转 CAD 任务（异步派发到 Celery sketch 队列）
- GET  /api/v1/sketches/{task_id}/result
    查询草图转 CAD 任务结果
- POST /api/v1/sketches/calibrate
    提交人工校准 + 重新生成任务
- GET  /api/v1/sketches/calibrate/{task_id}/result
    查询校准任务结果
- GET  /api/v1/sketches/files/{file_path:path}
    下载草图产物文件（DXF/STEP/STL）

设计原则：
- 异步路径走 Celery sketch 队列，复用 run_sketch_to_cad / run_sketch_calibration
- 始终标注 precision_level=sketch_level，提示用户人工校准
- 所有产物文件路径转换为相对下载 URL（/api/v1/sketches/files/...）
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse

from app.api.deps import CurrentUserDep, LoggerDep
from app.celery.task_registry import register_task
from app.celery.tasks.sketch import run_sketch_calibration, run_sketch_to_cad
from app.celery_app import celery_app
from app.config import settings
from app.logging import Logger
from app.schemas.sketch import (
    CalibrationRequest,
    CalibrationResult,
    SketchCreateRequest,
    SketchTaskAccepted,
    SketchTaskResult,
)

router = APIRouter()


# ===== 输出目录与 URL 转换 =====


def _sketch_output_root() -> Path:
    """草图模块的输出根目录（与 celery/tasks/sketch.py._SKETCH_OUTPUT_ROOT 对齐）。"""
    return Path(settings.UPLOAD_DIR).resolve() / "sketches"


def _to_download_url(file_path: str) -> str:
    """将绝对路径转换为下载 URL（相对路径）。"""
    try:
        p = Path(file_path).resolve()
        root = _sketch_output_root().resolve()
        rel = p.relative_to(root)
        return f"/api/v1/sketches/files/{rel.as_posix()}"
    except Exception:  # noqa: BLE001
        return file_path


# ===== 1. 提交草图转 CAD 任务 =====


@router.post(
    "",
    response_model=SketchTaskAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="提交草图转 CAD 任务（异步）",
)
async def create_sketch_to_cad(
    payload: SketchCreateRequest,
    user_id: str = CurrentUserDep,
    log: Logger = LoggerDep,
) -> JSONResponse:
    """提交草图转 CAD 任务到 Celery sketch 队列。

    流程：
    1. 接收已上传草图图片 file_key 与期望输出格式
    2. 派发 run_sketch_to_cad 任务（VLM 解析 + CadQuery 代码生成 + 沙箱执行）
    3. 返回 task_id（precision_level=sketch_level 强制标注）
    """
    if not payload.image_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="image_key is required",
        )

    log.info(
        "sketch.submitted",
        user=user_id,
        image_key=payload.image_key,
        output_format=payload.output_format,
    )

    async_result = run_sketch_to_cad.apply_async(
        kwargs={
            "image_key": payload.image_key,
            "user_id": user_id,
            "output_format": payload.output_format,
        },
        queue="sketch",
    )
    task_id = async_result.id
    register_task(task_id, "sketch")
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=SketchTaskAccepted(
            task_id=task_id,
            websocket_url=f"/api/v1/ws/tasks/{task_id}",
            precision_level="sketch_level",
        ).model_dump(),
    )


# ===== 2. 查询草图任务结果 =====


@router.get(
    "/{task_id}/result",
    response_model=SketchTaskResult,
    summary="查询草图转 CAD 任务结果",
)
async def get_sketch_result(
    task_id: str,
    log: Logger = LoggerDep,
) -> JSONResponse:
    """根据 task_id 查询草图转 CAD 任务结果。

    Celery 任务返回 dict（符合 SketchTaskResult schema），直接透传。
    所有 output_files 路径转换为下载 URL。
    """
    async_result = celery_app.AsyncResult(task_id)
    state = async_result.state

    if state == "PENDING":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"task {task_id} not found or pending",
        )
    if state in ("STARTED", "RETRY"):
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=SketchTaskResult(
                task_id=task_id,
                success=False,
                precision_level="sketch_level",
                warnings=[f"task still running (state={state})"],
                metadata={"state": state},
            ).model_dump(mode="json"),
        )
    if state == "FAILURE":
        err = str(async_result.result) if async_result.result else "task failed"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"task failed: {err}",
        )

    # SUCCESS
    result = async_result.result
    if not isinstance(result, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"unexpected result type: {type(result).__name__}",
        )

    # 兼容：确保 task_id 字段存在
    result.setdefault("task_id", task_id)
    # 强制 precision_level=sketch_level（spec.md R7）
    result["precision_level"] = "sketch_level"

    # 将 output_files 转换为下载 URL（保留原路径在 metadata 中）
    if "output_files" in result and isinstance(result["output_files"], list):
        original_paths = list(result["output_files"])
        result["output_files"] = [_to_download_url(p) for p in original_paths]
        meta = result.get("metadata") or {}
        meta.setdefault("original_output_paths", original_paths)
        result["metadata"] = meta

    log.info("sketch.result.fetched", task_id=task_id)
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


# ===== 3. 提交人工校准任务 =====


@router.post(
    "/calibrate",
    response_model=CalibrationResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="提交人工校准 + 重新生成任务",
)
async def calibrate_sketch(
    payload: CalibrationRequest,
    user_id: str = CurrentUserDep,
    log: Logger = LoggerDep,
) -> JSONResponse:
    """提交人工校准任务（基于原草图任务结果应用校准项并重新生成）。

    流程：
    1. 校验原草图任务已完成（sketch_task_id 状态为 SUCCESS）
    2. 派发 run_sketch_calibration 任务到 sketch 队列
    3. 返回校准任务 task_id
    """
    log.info(
        "sketch.calibrate.submitted",
        user=user_id,
        sketch_task_id=payload.sketch_task_id,
        calibrations_count=len(payload.calibrations),
    )

    # 校验原草图任务已完成
    original_async = celery_app.AsyncResult(payload.sketch_task_id)
    if original_async.state != "SUCCESS":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"原草图任务状态为 {original_async.state}，"
                f"需等待 SUCCESS 后才能派发校准（sketch_task_id={payload.sketch_task_id}）"
            ),
        )

    # 序列化 calibrations 为 dict 列表（Celery JSON 序列化要求）
    calibrations_dict = [c.model_dump(mode="json") for c in payload.calibrations]

    async_result = run_sketch_calibration.apply_async(
        kwargs={
            "sketch_task_id": payload.sketch_task_id,
            "calibrations": calibrations_dict,
            "user_id": user_id,
            "output_format": "dxf",  # 校准后默认 DXF（可编辑）
        },
        queue="sketch",
    )
    task_id = async_result.id
    register_task(task_id, "sketch")
    # 返回受理响应（实际结果需轮询 /calibrate/{task_id}/result）
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=CalibrationResult(
            task_id=task_id,
            success=False,  # 受理时尚未完成
            calibrated_features=[],
            regenerated_code="",
            output_files={},
            warnings=["校准任务已派发，请轮询 /calibrate/{task_id}/result 获取结果"],
        ).model_dump(mode="json"),
    )


# ===== 4. 查询校准任务结果 =====


@router.get(
    "/calibrate/{task_id}/result",
    response_model=CalibrationResult,
    summary="查询校准任务结果",
)
async def get_calibration_result(
    task_id: str,
    log: Logger = LoggerDep,
) -> JSONResponse:
    """查询 run_sketch_calibration 任务结果。"""
    async_result = celery_app.AsyncResult(task_id)
    state = async_result.state

    if state == "PENDING":
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=CalibrationResult(
                task_id=task_id,
                success=False,
                warnings=[f"task pending (state={state})"],
            ).model_dump(mode="json"),
        )
    if state in ("STARTED", "RETRY"):
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=CalibrationResult(
                task_id=task_id,
                success=False,
                warnings=[f"task still running (state={state})"],
            ).model_dump(mode="json"),
        )
    if state == "FAILURE":
        err = str(async_result.result) if async_result.result else "task failed"
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=CalibrationResult(
                task_id=task_id,
                success=False,
                warnings=[f"task failed: {err}"],
            ).model_dump(mode="json"),
        )

    # SUCCESS
    result = async_result.result
    if not isinstance(result, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"unexpected result type: {type(result).__name__}",
        )

    result.setdefault("task_id", task_id)

    # 将 output_files 转换为下载 URL
    if "output_files" in result and isinstance(result["output_files"], dict):
        original_paths = dict(result["output_files"])
        result["output_files"] = {
            k: _to_download_url(v) for k, v in original_paths.items()
        }
        meta = result.get("metadata") or {}
        meta.setdefault("original_output_paths", original_paths)
        result["metadata"] = meta

    log.info("sketch.calibrate.result.fetched", task_id=task_id)
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


# ===== 5. 产物文件下载 =====


@router.get(
    "/files/{file_path:path}",
    summary="下载草图产物文件",
)
async def download_sketch_file(file_path: str) -> FileResponse:
    """下载草图产物（DXF/STEP/STL 等）。"""
    root = _sketch_output_root().resolve()
    target = (root / file_path).resolve()
    # 防路径穿越
    try:
        target.relative_to(root)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid file path",
        ) from e
    if not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"file not found: {file_path}",
        )

    media_type = "application/octet-stream"
    suffix = target.suffix.lower()
    if suffix in (".step", ".stp"):
        media_type = "application/step"
    elif suffix == ".stl":
        media_type = "model/stl"
    elif suffix == ".dxf":
        media_type = "image/vnd.dxf"
    return FileResponse(path=str(target), media_type=media_type, filename=target.name)
