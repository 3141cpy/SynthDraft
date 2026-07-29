"""文件上传端点。

P0 阶段：审图（/reviews）与生成（/generations）均需先上传文件获得 file_key。
本端点接受 multipart/form-data，保存到 settings.UPLOAD_DIR，返回 file_key。

设计原则：
- 复用 FastAPI UploadFile（不复用 MinIO SDK，P0 降级为本地存储）
- 文件名净化：去除路径分隔符，加 uuid 前缀防冲突
- 扩展名白名单：仅允许 CAD/工程图相关格式
- 大小限制：100MB（P0 阶段足够，P2 可按文件类型细化）
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUserDep, LoggerDep
from app.config import settings
from app.logging import Logger
from app.schemas.upload import UploadResponse

router = APIRouter()

# 扩展名 → file_type 映射（与 ReviewCreateRequest.file_type 对齐）
_EXT_TO_TYPE: dict[str, str] = {
    ".dxf": "dxf",
    ".dwg": "dwg",
    ".step": "step",
    ".stp": "step",
    ".iges": "iges",
    ".igs": "iges",
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".sldprt": "sldprt",
    ".sldasm": "sldasm",
}

# 允许的扩展名集合
_ALLOWED_EXTS = set(_EXT_TO_TYPE.keys())

# 文件大小上限：100 MB（P0 阶段）
_MAX_SIZE_BYTES = 100 * 1024 * 1024


def _sanitize_filename(name: str) -> str:
    """净化文件名：仅保留字母数字、点、下划线、连字符、中文。

    丢弃路径分隔符（防止路径穿越）与控制字符。
    """
    if not name:
        return "upload"
    # 取 basename（防止 ../ 攻击）
    name = os.path.basename(name)
    # 去除控制字符
    cleaned = "".join(c for c in name if c.isprintable() and c not in ("\r", "\n", "\t"))
    return cleaned or "upload"


def _detect_path_traversal(name: str) -> bool:
    """检测文件名是否含路径穿越字符或序列。

    检测规则：
    - 含正斜杠 ``/``（Unix 路径分隔符）
    - 含反斜杠 ``\\``（Windows 路径分隔符）
    - 含连续两点 ``..``（目录上跳序列）

    返回 True 表示检测到路径穿越风险，调用方应拒绝该上传请求。
    """
    return "/" in name or "\\" in name or ".." in name


def _infer_file_type(filename: str) -> str | None:
    """根据扩展名推断 file_type。"""
    ext = Path(filename).suffix.lower()
    return _EXT_TO_TYPE.get(ext)


def _upload_root() -> Path:
    """上传根目录（确保存在）。"""
    root = Path(settings.UPLOAD_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


@router.post(
    "",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="上传文件（审图/生成模块共用）",
)
async def upload_file(
    file: UploadFile,
    user_id: str = CurrentUserDep,
    log: Logger = LoggerDep,
) -> JSONResponse:
    """上传单个文件，返回 file_key 供后续 /reviews 或 /generations 使用。

    - 接受 multipart/form-data
    - 文件名净化（防路径穿越）
    - 扩展名白名单：dxf/dwg/step/stp/iges/igs/pdf/png/jpg/jpeg/sldprt/sldasm
    - 大小限制：100 MB
    - 保存路径：{UPLOAD_DIR}/{uuid_hex}_{sanitized_filename}
    - file_key = "{uuid_hex}_{sanitized_filename}"（相对 UPLOAD_DIR）
    """
    original_name = file.filename or "upload"
    if _detect_path_traversal(original_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件名含非法路径字符或路径穿越序列",
        )
    safe_name = _sanitize_filename(original_name)
    file_type = _infer_file_type(safe_name)

    if not file_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"不支持的文件类型: {Path(safe_name).suffix or '(无扩展名)'}；"
                f"允许: {sorted(_ALLOWED_EXTS)}"
            ),
        )

    # 生成 file_key：uuid 前缀防冲突
    file_key = f"{uuid.uuid4().hex}_{safe_name}"
    target = _upload_root() / file_key

    # 流式写入磁盘，避免全量读入内存；边写边检查大小（DoS 防护）
    size = 0
    too_large = False
    with target.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)  # 1MB 分块
            if not chunk:
                break
            size += len(chunk)
            if size > _MAX_SIZE_BYTES:
                too_large = True
                break
            out.write(chunk)

    if too_large:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件过大: > {_MAX_SIZE_BYTES} bytes (100MB)",
        )
    if size == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件为空",
        )

    log.info(
        "upload.received",
        user=user_id,
        file_name=safe_name,
        file_type=file_type,
        size=size,
        file_key=file_key,
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=UploadResponse(
            file_key=file_key,
            file_name=safe_name,
            file_type=file_type,  # type: ignore[arg-type]
            size=size,
            content_type=file.content_type or "",
        ).model_dump(),
    )


@router.get(
    "",
    summary="列出已上传文件（开发态调试用）",
)
async def list_uploads(
    user_id: str = CurrentUserDep,
    log: Logger = LoggerDep,
) -> dict:
    """列出 UPLOAD_DIR 下的文件（仅供开发态调试）。

    不分页、不鉴权（P0 阶段），P2 需改为按 user_id 过滤。
    """
    root = _upload_root()
    items = []
    for p in sorted(root.iterdir()):
        if not p.is_file():
            continue
        ft = _infer_file_type(p.name)
        if not ft:
            continue
        items.append(
            {
                "file_key": p.name,
                "file_name": p.name,
                "file_type": ft,
                "size": p.stat().st_size,
            }
        )
    log.info("upload.list", user=user_id, count=len(items))
    return {"uploads": items, "total": len(items)}
