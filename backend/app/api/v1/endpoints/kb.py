"""知识库 API 端点。

提供规范条款检索、已索引规范列表、重建索引三个端点。
遵循"以复用现有为荣"原则，复用 HybridClauseRetriever 与 indexer。

Task 14 新增端点：
- POST /enterprise-standards/import：上传企业规范文件并导入
- GET  /standards/conflicts：检测两个规范集冲突
- GET  /profiles：列出所有规范配置
- POST /profiles/active：切换当前活跃配置
- POST /profiles：创建新规范配置

Task 15 新增端点：
- GET  /standards/library：列出预置规范库
- GET  /standards/library/{category}：按类别列出预置规范
- GET  /standards/versions?standard_id=...：列出某规范所有版本
- POST /standards/versions?standard_id=...：注册新版本
- GET  /standards/notifications：列出更新通知

注：/standards/versions 端点的 standard_id 作为 query 参数传递，避免 URL 编码的 '/'（%2F）
在 path param 中被 Starlette/uvicorn 解码为 '/' 导致路由不匹配。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from app.api.deps import get_current_user_id
from app.config import settings
from app.logging import get_logger
from app.schemas.kb import (
    ClausesQueryResponse,
    ConflictReport,
    EnterpriseImportResponse,
    PresetStandard,
    ProfileCreateRequest,
    ProfileListResponse,
    ProfileSetActiveRequest,
    ReindexResponse,
    StandardCategory,
    StandardNotification,
    StandardProfile,
    StandardVersion,
    StandardsListResponse,
    VersionDiff,
    VersionRegisterRequest,
)
from app.services.kb.conflict_detector import detect_conflicts
from app.services.kb.enterprise_import import import_enterprise_standard
from app.services.kb.qdrant_store import get_store
from app.services.kb.retriever import HybridClauseRetriever, get_retriever
from app.services.kb.indexer import DEFAULT_COLLECTION, build_index_from_markdown
from app.services.kb.standard_library import get_library
from app.services.kb.standard_profile import (
    StandardProfileManager,
    get_manager,
)
from app.services.kb.version_manager import (
    get_notifier,
    get_version_manager,
)

router = APIRouter()
log = get_logger(__name__)


def _kb_standards_dir() -> Path:
    """获取 kb/standards 目录绝对路径。

    kb.py 位于 d:\\SynthDraft\\backend\\app\\api\\v1\\endpoints\\kb.py：
      - parents[3] = d:\\SynthDraft\\backend\\app
      - parents[4] = d:\\SynthDraft\\backend
      - parents[5] = d:\\SynthDraft
    kb 目录在项目根下，与 backend 平级：d:\\SynthDraft\\kb\\standards。
    """
    project_root = Path(__file__).resolve().parents[5]  # d:\SynthDraft
    return project_root / "kb" / "standards"


@router.get(
    "/clauses",
    response_model=ClausesQueryResponse,
    summary="规范条款检索",
    description=(
        "按自然语言查询检索工程规范条款，支持按规范编号与分类过滤。"
        "每条结果强制包含原文片段（original_text）与来源文件（source_file），"
        "缺失时标注 completeness=incomplete。"
    ),
)
async def search_clauses(
    query: str = Query(..., min_length=1, description="查询文本"),
    top_k: int = Query(5, ge=1, le=50, description="返回条数"),
    standard: str | None = Query(None, description="规范编号过滤，逗号分隔"),
    category: str | None = Query(None, description="分类过滤，逗号分隔"),
    clause_id: str | None = Query(None, description="条款号精确匹配（如 5.2.1）"),
) -> ClausesQueryResponse:
    retriever: HybridClauseRetriever = get_retriever()
    standard_filter = (
        [s.strip() for s in standard.split(",") if s.strip()] if standard else None
    )
    category_filter = (
        [c.strip() for c in category.split(",") if c.strip()] if category else None
    )

    try:
        results = retriever.retrieve(
            query=query,
            top_k=top_k,
            standard_filter=standard_filter,
            category_filter=category_filter,
            clause_id_filter=clause_id,
        )
    except Exception as e:  # noqa: BLE001
        log.error("kb.clauses.search_failed", error=str(e), query=query)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"知识库检索失败：{e}",
        ) from e

    return ClausesQueryResponse(
        query=query,
        top_k=top_k,
        results=results,
        total=len(results),
    )


@router.get(
    "/standards",
    response_model=StandardsListResponse,
    summary="已索引规范列表",
    description="返回当前 Qdrant collection 中已索引的规范编号列表。",
)
async def list_standards() -> StandardsListResponse:
    store = get_store()
    try:
        standards = store.list_standards(DEFAULT_COLLECTION)
    except Exception as e:  # noqa: BLE001
        log.error("kb.standards.list_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"获取规范列表失败：{e}",
        ) from e

    return StandardsListResponse(standards=standards, count=len(standards))


@router.post(
    "/reindex",
    response_model=ReindexResponse,
    summary="重建索引",
    description=(
        "从 kb/standards/ 目录重新构建向量索引。"
        "会删除并重建 Qdrant collection。"
    ),
)
async def reindex(user_id: str = Depends(get_current_user_id)) -> ReindexResponse:
    standards_dir = _kb_standards_dir()
    if not standards_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"样本目录不存在：{standards_dir}",
        )

    log.info("kb.reindex.start", dir=str(standards_dir))
    try:
        indexed = build_index_from_markdown(
            md_dir=standards_dir,
            collection_name=DEFAULT_COLLECTION,
            # /reindex 语义即"删除并重建"，显式传 True 以清理旧向量，
            # 避免已删除条款残留脏数据。其余增量场景默认 False。
            recreate=True,
        )
    except Exception as e:  # noqa: BLE001
        log.error("kb.reindex.failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"重建索引失败：{e}",
        ) from e

    return ReindexResponse(
        indexed_count=indexed,
        collection=DEFAULT_COLLECTION,
        message=f"已从 {standards_dir.name} 重建索引",
    )


# ===========================================================================
# Task 14：企业规范自定义
# ===========================================================================


@router.post(
    "/enterprise-standards/import",
    response_model=EnterpriseImportResponse,
    summary="上传并导入企业规范文件",
    description=(
        "支持 PDF / Word(.docx) / Excel(.xlsx) 三种格式，"
        "解析为统一的结构化条文 ClauseRecord 列表。"
        "Excel 约定列：[条款号, 标题, 正文, 关键词, 引用]。"
    ),
)
async def import_enterprise_standard_endpoint(
    user_id: str = Depends(get_current_user_id),
    file: UploadFile = File(..., description="企业规范文件"),
    standard: str = Query(..., description="规范编号或名称，如 Q/XX 001-2024"),
    version: str = Query("", description="规范版本年份（留空自动推断）"),
) -> EnterpriseImportResponse:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少文件名",
        )

    # 落地到临时文件（pdfplumber / python-docx / openpyxl 均需文件路径）
    suffix = Path(file.filename).suffix.lower()
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, prefix="enterprise_std_"
        ) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
    except Exception as e:  # noqa: BLE001
        log.error("kb.enterprise_import.save_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存上传文件失败：{e}",
        ) from e

    try:
        records = import_enterprise_standard(
            file_path=tmp_path,
            standard_name=standard,
            version=version,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except ImportError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except Exception as e:  # noqa: BLE001
        log.error("kb.enterprise_import.failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导入失败：{e}",
        ) from e
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    fmt = suffix.lstrip(".").lower()
    return EnterpriseImportResponse(
        standard=standard,
        version=version or records[0].version if records else "",
        source_file=file.filename,
        format=fmt,
        clauses_count=len(records),
        clauses=records[:50],  # 限制响应体大小，仅返回前 50 条
        message=f"成功提取 {len(records)} 条条款",
    )


@router.get(
    "/standards/conflicts",
    response_model=ConflictReport,
    summary="规范集冲突检测",
    description=(
        "检测两个规范集之间的条文冲突（矛盾/重复/缺失/增强）。"
        "支持 LLM + 关键词双重检测；LLM 不可用时仅用关键词匹配。"
        "从 Qdrant 拉取双方已索引条款进行对比。"
    ),
)
async def detect_standard_conflicts(
    standard_a: str = Query(..., description="规范集 A 编号（通常国标）"),
    standard_b: str = Query(..., description="规范集 B 编号（通常企业标准）"),
    use_llm: bool = Query(True, description="是否启用 LLM 检测"),
) -> ConflictReport:
    store = get_store()
    try:
        # 从 Qdrant 拉取双方条款
        clauses_a = _fetch_clauses_by_standard(store, standard_a)
        clauses_b = _fetch_clauses_by_standard(store, standard_b)
    except Exception as e:  # noqa: BLE001
        log.error("kb.conflicts.fetch_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"获取规范条款失败：{e}",
        ) from e

    if not clauses_a:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"规范集 A {standard_a!r} 在 Qdrant 中无条款",
        )
    if not clauses_b:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"规范集 B {standard_b!r} 在 Qdrant 中无条款",
        )

    try:
        report = detect_conflicts(
            clauses_a=clauses_a,
            clauses_b=clauses_b,
            standard_a=standard_a,
            standard_b=standard_b,
            use_llm=use_llm,
        )
    except Exception as e:  # noqa: BLE001
        log.error("kb.conflicts.detect_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"冲突检测失败：{e}",
        ) from e

    return report


def _fetch_clauses_by_standard(store, standard: str):
    """从 Qdrant 按 standard 字段拉取全部条款（scroll + payload 过滤）。"""
    from qdrant_client.http import models as qmodels

    seen_ids: set[str] = set()
    clauses: list = []
    offset = None
    while True:
        resp = store.client.scroll(
            collection_name=DEFAULT_COLLECTION,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="standard",
                        match=qmodels.MatchValue(value=standard),
                    )
                ]
            ),
        )
        points, next_offset = resp[0], resp[1]
        if not points:
            break
        for p in points:
            payload = p.payload or {}
            cid = str(payload.get("clause_id", ""))
            key = f"{standard}|{cid}"
            if key in seen_ids:
                continue
            seen_ids.add(key)
            from app.schemas.kb import ClauseRecord

            clauses.append(
                ClauseRecord(
                    standard=payload.get("standard", standard),
                    clause_id=cid,
                    title=payload.get("title", ""),
                    category=payload.get("category", "general"),
                    keywords=payload.get("keywords", []),
                    references=payload.get("references", []),
                    version=payload.get("version", ""),
                    is_sample=payload.get("is_sample", False),
                    original_text=payload.get("original_text", ""),
                    source_file=payload.get("source_file", ""),
                )
            )
        offset = next_offset
        if offset is None:
            break
    return clauses


@router.get(
    "/profiles",
    response_model=ProfileListResponse,
    summary="列出所有规范配置",
    description="返回当前持久化的所有规范配置（国标集/企业标准集/行业标准集）。",
)
async def list_standard_profiles() -> ProfileListResponse:
    mgr = get_manager()
    try:
        profiles = mgr.list_profiles()
    except Exception as e:  # noqa: BLE001
        log.error("kb.profiles.list_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"获取规范配置失败：{e}",
        ) from e

    active = mgr.get_active_profile()
    return ProfileListResponse(
        profiles=profiles,
        active_profile=active.name if active else "",
        total=len(profiles),
    )


@router.post(
    "/profiles",
    response_model=StandardProfile,
    summary="创建规范配置",
    description="创建新的规范配置（同名覆盖）。",
)
async def create_standard_profile(
    req: ProfileCreateRequest,
    user_id: str = Depends(get_current_user_id),
) -> StandardProfile:
    mgr = get_manager()
    try:
        profile = mgr.create_profile(
            name=req.name,
            standards=req.standards,
            description=req.description,
            priority=req.priority,
        )
    except Exception as e:  # noqa: BLE001
        log.error("kb.profiles.create_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建规范配置失败：{e}",
        ) from e
    return profile


@router.post(
    "/profiles/active",
    response_model=ProfileListResponse,
    summary="切换当前活跃配置",
    description="切换当前活跃规范配置；切换后 RAG 检索默认使用此配置中的规范编号过滤。",
)
async def set_active_standard_profile(
    req: ProfileSetActiveRequest,
    user_id: str = Depends(get_current_user_id),
) -> ProfileListResponse:
    mgr = get_manager()
    try:
        ok = mgr.set_active_profile(req.name)
    except Exception as e:  # noqa: BLE001
        log.error("kb.profiles.set_active_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"切换活跃配置失败：{e}",
        ) from e

    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"规范配置不存在：{req.name}",
        )

    profiles = mgr.list_profiles()
    return ProfileListResponse(
        profiles=profiles,
        active_profile=req.name,
        total=len(profiles),
    )


# ===========================================================================
# Task 15：规范知识库扩展（预置规范库 + 版本管理 + 更新通知）
# ===========================================================================


@router.get(
    "/standards/library",
    response_model=list[PresetStandard],
    summary="预置规范库列表",
    description=(
        "返回内置的预置规范元数据清单，覆盖国标（GB/T）、国际标准（ISO）、"
        "行业标准（JB/T、HG/T、QC/T 等）。可通过 ``category`` 参数过滤。"
    ),
)
async def list_preset_standards_library(
    category: StandardCategory | None = Query(
        None, description="按类别过滤：national/industry/international/enterprise"
    ),
) -> list[PresetStandard]:
    lib = get_library()
    try:
        return lib.list_preset_standards(category=category)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get(
    "/standards/library/{category}",
    response_model=list[PresetStandard],
    summary="按类别列出预置规范",
    description=(
        "按类别列出预置规范库。合法类别："
        "national / industry / international / enterprise。"
    ),
)
async def list_preset_standards_by_category(
    category: str,
) -> list[PresetStandard]:
    lib = get_library()
    try:
        return lib.list_standards_by_category(category)  # type: ignore[arg-type]
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get(
    "/standards/versions",
    response_model=list[StandardVersion],
    summary="列出某规范所有版本",
    description=(
        "返回指定规范在版本管理器中已注册的所有版本记录，按版本号降序。"
        "standard_id 既可带年份（如 GB/T 4458.4-2003），也可只给基线编号"
        "（如 GB/T 4458.4）。"
        "standard_id 作为 query 参数传递，避免 URL 编码的 '/' 导致路由不匹配。"
    ),
)
async def list_standard_versions(
    standard_id: str = Query(
        ..., description="规范编号，如 GB/T 4458.4 或 GB/T 4458.4-2003"
    ),
) -> list[StandardVersion]:
    mgr = get_version_manager()
    try:
        return mgr.list_versions(standard_id)
    except Exception as e:  # noqa: BLE001
        log.error("kb.versions.list_failed", standard_id=standard_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"获取版本列表失败：{e}",
        ) from e


@router.post(
    "/standards/versions",
    response_model=StandardVersion,
    summary="注册规范新版本",
    description=(
        "为指定规范注册一个新版本。若 status=active，已有 active 版本会自动标记为 superseded。"
        "同 (standard_id, version) 覆盖。"
        "standard_id 作为 query 参数传递，避免 URL 编码的 '/' 导致路由不匹配。"
    ),
)
async def register_standard_version(
    req: VersionRegisterRequest,
    standard_id: str = Query(
        ..., description="规范编号，如 GB/T 4458.4 或 GB/T 4458.4-2003"
    ),
    user_id: str = Depends(get_current_user_id),
) -> StandardVersion:
    mgr = get_version_manager()
    try:
        return mgr.register_version(
            standard_id=standard_id,
            version=req.version,
            release_date=req.release_date,
            status=req.status,
            notes=req.notes,
        )
    except Exception as e:  # noqa: BLE001
        log.error(
            "kb.versions.register_failed",
            standard_id=standard_id,
            version=req.version,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"注册版本失败：{e}",
        ) from e


@router.get(
    "/standards/notifications",
    response_model=list[StandardNotification],
    summary="列出规范更新通知",
    description=(
        "返回所有规范更新通知，按创建时间倒序。可通过 ``only_unread`` 仅返回未读。"
    ),
)
async def list_standard_notifications(
    only_unread: bool = Query(False, description="仅返回未读通知"),
) -> list[StandardNotification]:
    notifier = get_notifier()
    try:
        return notifier.list_notifications(only_unread=only_unread)
    except Exception as e:  # noqa: BLE001
        log.error("kb.notifications.list_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"获取通知列表失败：{e}",
        ) from e
