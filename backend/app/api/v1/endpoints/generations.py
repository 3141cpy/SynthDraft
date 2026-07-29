"""生成端点（Task 5）。

提供三个端点：
- POST /api/v1/generations           异步提交生成任务（Celery）
- GET  /api/v1/generations/{id}/result  查询生成结果
- POST /api/v1/generations/execute   同步执行用户编辑后的代码（沙箱）

设计原则：
- 异步路径走 Celery，复用现有 ``run_generation`` 任务
- 同步路径供 Monaco Editor 重新执行使用，直接调用沙箱（不经过 Celery）
- 所有产出文件路径转换为相对下载 URL（/api/v1/generations/files/...）
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse

from app.api.deps import CurrentUserDep, LoggerDep
from app.celery.task_registry import register_task
from app.celery.tasks.generations import run_generation
from app.config import settings
from app.logging import Logger
from app.schemas.generation import (
    GenerationCreateRequest,
    GenerationTaskAccepted,
)
from app.schemas.generation_detail import (
    ExecuteCodeRequest,
    ExecuteCodeResponse,
    GenerationResult,
)
from app.services.generation import execute_cadquery_code, validate_step_file

router = APIRouter()


# ===== 临时输出目录 =====


def _output_root() -> Path:
    """生成模块的临时输出根目录（每次执行一个子目录）。"""
    root = Path(settings.UPLOAD_DIR).resolve() / "generations"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _to_download_url(file_path: str) -> str:
    """将绝对路径转换为下载 URL（相对路径）。"""
    try:
        p = Path(file_path).resolve()
        root = _output_root().resolve()
        rel = p.relative_to(root)
        return f"/api/v1/generations/files/{rel.as_posix()}"
    except Exception:  # noqa: BLE001
        return file_path


# ===== 1. 异步提交生成任务 =====


@router.post(
    "",
    response_model=GenerationTaskAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="提交生成任务（异步）",
)
async def create_generation(
    payload: GenerationCreateRequest,
    user_id: str = CurrentUserDep,
    log: Logger = LoggerDep,
) -> JSONResponse:
    """提交生成任务到 Celery generations 队列。"""
    if payload.input_type == "text" and not payload.prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="prompt is required when input_type=text",
        )
    if payload.input_type == "sketch" and not payload.sketch_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sketch_key is required when input_type=sketch",
        )

    log.info(
        "generation.submitted",
        user=user_id,
        input_type=payload.input_type,
        output_format=payload.output_format,
    )
    async_result = run_generation.apply_async(
        kwargs={
            "input_type": payload.input_type,
            "prompt": payload.prompt,
            "sketch_key": payload.sketch_key,
            "output_format": payload.output_format,
            "user_id": user_id,
        },
        queue="generations",
    )
    task_id = async_result.id
    register_task(task_id, "generation")
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=GenerationTaskAccepted(
            task_id=task_id,
            websocket_url=f"/api/v1/ws/tasks/{task_id}",
        ).model_dump(),
    )


# ===== 2. 查询生成结果 =====


@router.get(
    "/{task_id}/result",
    response_model=GenerationResult,
    summary="查询生成任务结果",
)
async def get_generation_result(
    task_id: str,
    log: Logger = LoggerDep,
) -> JSONResponse:
    """根据 task_id 查询生成结果。

    Celery 任务返回 dict（符合 GenerationResult schema），直接透传。
    """
    from app.celery_app import celery_app

    async_result = celery_app.AsyncResult(task_id)
    state = async_result.state

    if state == "PENDING":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"task {task_id} not found or pending",
        )
    if state == "STARTED" or state == "RETRY":
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=GenerationResult(
                task_id=task_id,
                input_prompt="",
                generated_code="",
                metadata={"state": state, "message": "task still running"},
            ).model_dump(),
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
    log.info("generation.result.fetched", task_id=task_id)
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


# ===== 3. 同步执行用户编辑后的代码 =====


@router.post(
    "/execute",
    response_model=ExecuteCodeResponse,
    summary="同步执行用户编辑后的 CadQuery 代码",
)
async def execute_edited_code(
    payload: ExecuteCodeRequest,
    log: Logger = LoggerDep,
) -> JSONResponse:
    """接收 Monaco Editor 编辑后的 CadQuery 代码，沙箱同步执行。

    - 静态扫描拒绝危险代码
    - subprocess + timeout 隔离执行
    - 自动产出 STEP/STL 并返回下载 URL
    """
    run_id = uuid.uuid4().hex[:12]
    out_dir = _output_root() / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info(
        "generation.execute.sync",
        run_id=run_id,
        code_len=len(payload.code),
        output_format=payload.output_format,
    )

    execution = await asyncio.to_thread(
        execute_cadquery_code,
        code=payload.code,
        output_dir=out_dir,
        timeout=payload.timeout,
        output_format=payload.output_format,
    )

    # 几何校验（仅 STEP 文件存在时）
    geo_val = None
    step_files = [p for p in execution.output_files if p.lower().endswith((".step", ".stp"))]
    if step_files:
        geo_val = await asyncio.to_thread(validate_step_file, Path(step_files[0]))

    download_urls = [_to_download_url(p) for p in execution.output_files]

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=ExecuteCodeResponse(
            execution=execution,
            geometry_validation=geo_val,
            download_urls=download_urls,
        ).model_dump(),
    )


# ===== 4. 产出文件下载 =====


@router.get(
    "/files/{file_path:path}",
    summary="下载生成产物文件",
)
async def download_generated_file(file_path: str) -> FileResponse:
    """下载生成产物（STEP/STL/DXF 等）。"""
    root = _output_root().resolve()
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
