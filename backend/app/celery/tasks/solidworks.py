"""Celery solidworks 队列任务（SubTask 7.5）。

实现 Linux AI 服务 ↔ Windows SolidWorks Worker 的消息队列通信：
- Linux AI 服务通过 Celery 投递任务到 ``solidworks`` 队列
- Windows Worker（装有 SolidWorks 许可证）消费队列、调用 SolidWorks API
- 结果通过 Celery result backend（Redis）回传给 AI 服务

设计原则（遵循"以瞎猜接口为耻" + "跨平台降级"）：
- 所有任务在 Linux/无 pywin32 环境下返回降级结果 dict（``success=False``），
  不抛异常、不触发 Celery 重试风暴
- 实际 SolidWorks API 调用委托给 ``app.services.solidworks.reader/writer``，
  这些函数已通过 ``@solidworks_task`` 装饰器自动管理 Worker Pool 生命周期
  （懒启动 + 健康检查 + 超时重启 + 许可证计数）
- 仅对瞬时错误（``SolidWorksTaskTimeout`` / ``SolidWorksSessionError``）自动重试，
  平台/许可证错误不重试（重试无意义）
- 返回值统一为 JSON 可序列化 dict，便于跨平台传输

任务清单（6 个）：
1. ``read_sldprt_task``            远程读取 SLDPRT
2. ``read_sldasm_task``            远程读取 SLDASM
3. ``generate_sldprt_from_cadquery_task``   CadQuery 代码 → SLDPRT
4. ``generate_sldprt_from_features_task``   特征描述 → SLDPRT
5. ``generate_sldasm_from_components_task`` 组件列表 → SLDASM
6. ``license_status_task``         查询 SolidWorks 许可证状态（轻量，供 AI 服务调度前探测）

队列路由（见 app/celery_app.py）：
    "app.celery.tasks.solidworks.*": {"queue": "solidworks"}

启动 Worker（Windows 端）：
    celery -A app.celery_app worker -Q solidworks -c 1 --without-gossip
注：``-c 1`` 单并发（SolidWorks COM 是 STA，许可证通常限单实例）；
    ``--without-gossip`` 降低 broker 压力。

参考：
- Celery 5.x 文档：https://docs.celeryq.dev/en/stable/
- spec.md §"系统架构设计"（AI 服务无状态、SolidWorks Worker 有状态）
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from app.celery.base import BaseTask
from app.celery_app import celery_app
from app.logging import get_logger
from app.services.solidworks.exceptions import (
    SolidWorksLicenseError,
    SolidWorksNotAvailableError,
    SolidWorksSessionError,
    SolidWorksTaskError,
    SolidWorksTaskTimeout,
)
from app.services.solidworks.sw_session import is_solidworks_available

log = get_logger(__name__)

# ===== 任务超时配置（秒）=====
# 硬超时 5 分钟（SolidWorks Dispatch 启动 ~10s + 文件操作 + 保存）
_TASK_TIME_LIMIT = 300
# 软超时 4.5 分钟（留 30s 给优雅退出 + 资源清理）
_TASK_SOFT_TIME_LIMIT = 270
# 瞬时错误最大重试次数（避免重试风暴）
_MAX_RETRIES = 2


# ===== 通用工具 =====


def _degraded_result(
    task_id: str,
    task_name: str,
    reason: str,
    message: str,
    elapsed_ms: int = 0,
) -> dict[str, Any]:
    """构造降级结果 dict（不抛异常，由调用方根据 success 字段判断）。

    Args:
        task_id: Celery 任务 ID
        task_name: 任务名（用于日志与监控）
        reason: 降级原因码（如 "solidworks_unavailable" / "license_error"）
        message: 人类可读的错误信息
        elapsed_ms: 已耗时（毫秒）

    Returns:
        标准降级结果 dict
    """
    return {
        "task_id": task_id,
        "task_name": task_name,
        "success": False,
        "error": reason,
        "message": message,
        "elapsed_ms": elapsed_ms,
        "result": None,
    }


def _success_result(
    task_id: str,
    task_name: str,
    result: Any,
    elapsed_ms: int,
) -> dict[str, Any]:
    """构造成功结果 dict。

    Args:
        task_id: Celery 任务 ID
        task_name: 任务名
        result: 业务结果（必须 JSON 可序列化）
        elapsed_ms: 已耗时（毫秒）

    Returns:
        标准成功结果 dict
    """
    return {
        "task_id": task_id,
        "task_name": task_name,
        "success": True,
        "error": None,
        "message": None,
        "elapsed_ms": elapsed_ms,
        "result": result,
    }


# ===== 任务 1：read_sldprt_task =====


@celery_app.task(
    name="app.celery.tasks.solidworks.read_sldprt",
    bind=True,
    base=BaseTask,
    autoretry_for=(SolidWorksTaskTimeout, SolidWorksSessionError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=_MAX_RETRIES,
    acks_late=True,
    time_limit=_TASK_TIME_LIMIT,
    soft_time_limit=_TASK_SOFT_TIME_LIMIT,
)
def read_sldprt_task(self: BaseTask, file_path: str) -> dict[str, Any]:
    """远程读取 SLDPRT 文件并返回结构化模型。

    Args:
        file_path: SLDPRT 文件路径（Worker 端本地路径或网络共享路径）

    Returns:
        标准结果 dict。``result`` 字段为 SolidWorksModel.model_dump() 或 None。
    """
    task_id = self.request.id or "unknown"
    task_name = "read_sldprt"
    t_start = time.perf_counter()
    log.info("sw.task.read_sldprt.start", task_id=task_id, file_path=file_path)

    if not is_solidworks_available():
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.warning(
            "sw.task.read_sldprt.unavailable",
            task_id=task_id,
            platform=_platform_info(),
        )
        return _degraded_result(
            task_id, task_name, "solidworks_unavailable",
            "pywin32 未安装或非 Windows 平台，无法读取 SLDPRT",
            elapsed_ms=elapsed_ms,
        )

    try:
        # 延迟导入避免模块加载时触发 pywin32 检测（已在 is_solidworks_available 兜底）
        from app.services.solidworks import read_sldprt

        model = read_sldprt(Path(file_path))
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.info(
            "sw.task.read_sldprt.done",
            task_id=task_id,
            elapsed_ms=elapsed_ms,
            features=len(model.features),
            dimensions=len(model.dimensions),
        )
        return _success_result(
            task_id, task_name,
            result=model.model_dump(mode="json"),
            elapsed_ms=elapsed_ms,
        )
    except (SolidWorksNotAvailableError, SolidWorksLicenseError) as e:
        # 不可重试的错误：直接返回降级结果
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.warning(
            "sw.task.read_sldprt.degraded",
            task_id=task_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return _degraded_result(
            task_id, task_name, type(e).__name__, str(e), elapsed_ms=elapsed_ms,
        )
    except (SolidWorksTaskTimeout, SolidWorksSessionError, SolidWorksTaskError) as e:
        # 可重试 / 业务错误：记日志后向上抛，由 Celery autoretry_for 决定是否重试
        # SolidWorksTaskError 不在 autoretry_for 中，会直接标记 FAILED
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.error(
            "sw.task.read_sldprt.error",
            task_id=task_id,
            error_type=type(e).__name__,
            error=str(e),
            elapsed_ms=elapsed_ms,
        )
        raise


# ===== 任务 2：read_sldasm_task =====


@celery_app.task(
    name="app.celery.tasks.solidworks.read_sldasm",
    bind=True,
    base=BaseTask,
    autoretry_for=(SolidWorksTaskTimeout, SolidWorksSessionError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=_MAX_RETRIES,
    acks_late=True,
    time_limit=_TASK_TIME_LIMIT,
    soft_time_limit=_TASK_SOFT_TIME_LIMIT,
)
def read_sldasm_task(self: BaseTask, file_path: str) -> dict[str, Any]:
    """远程读取 SLDASM 装配体文件并返回结构化模型（含组件/配合/BOM）。

    Args:
        file_path: SLDASM 文件路径

    Returns:
        标准结果 dict。``result`` 字段为 SolidWorksModel.model_dump() 或 None。
    """
    task_id = self.request.id or "unknown"
    task_name = "read_sldasm"
    t_start = time.perf_counter()
    log.info("sw.task.read_sldasm.start", task_id=task_id, file_path=file_path)

    if not is_solidworks_available():
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.warning(
            "sw.task.read_sldasm.unavailable",
            task_id=task_id,
            platform=_platform_info(),
        )
        return _degraded_result(
            task_id, task_name, "solidworks_unavailable",
            "pywin32 未安装或非 Windows 平台，无法读取 SLDASM",
            elapsed_ms=elapsed_ms,
        )

    try:
        from app.services.solidworks import read_sldasm

        model = read_sldasm(Path(file_path))
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.info(
            "sw.task.read_sldasm.done",
            task_id=task_id,
            elapsed_ms=elapsed_ms,
            components=len(model.components),
            mates=len(model.mates),
            bom_items=len(model.bom_items),
        )
        return _success_result(
            task_id, task_name,
            result=model.model_dump(mode="json"),
            elapsed_ms=elapsed_ms,
        )
    except (SolidWorksNotAvailableError, SolidWorksLicenseError) as e:
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.warning(
            "sw.task.read_sldasm.degraded",
            task_id=task_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return _degraded_result(
            task_id, task_name, type(e).__name__, str(e), elapsed_ms=elapsed_ms,
        )
    except (SolidWorksTaskTimeout, SolidWorksSessionError, SolidWorksTaskError) as e:
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.error(
            "sw.task.read_sldasm.error",
            task_id=task_id,
            error_type=type(e).__name__,
            error=str(e),
            elapsed_ms=elapsed_ms,
        )
        raise


# ===== 任务 3：generate_sldprt_from_cadquery_task =====


@celery_app.task(
    name="app.celery.tasks.solidworks.generate_sldprt_from_cadquery",
    bind=True,
    base=BaseTask,
    autoretry_for=(SolidWorksTaskTimeout, SolidWorksSessionError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=_MAX_RETRIES,
    acks_late=True,
    time_limit=_TASK_TIME_LIMIT,
    soft_time_limit=_TASK_SOFT_TIME_LIMIT,
)
def generate_sldprt_from_cadquery_task(
    self: BaseTask,
    code: str,
    output_path: str,
    cadquery_timeout: int = 60,
) -> dict[str, Any]:
    """从 CadQuery 代码生成 SLDPRT（路径 A：CadQuery → STEP → SolidWorks 导入）。

    Args:
        code: CadQuery Python 代码（必须定义变量 ``result``，类型为 cq.Workplane）
        output_path: 输出 SLDPRT 文件路径（Worker 端本地路径）
        cadquery_timeout: CadQuery 沙箱执行超时（秒），默认 60

    Returns:
        标准结果 dict。``result`` 字段为 {"output_path": str} 或 None。
    """
    task_id = self.request.id or "unknown"
    task_name = "generate_sldprt_from_cadquery"
    t_start = time.perf_counter()
    log.info(
        "sw.task.generate_sldprt_cadquery.start",
        task_id=task_id,
        output_path=output_path,
        code_len=len(code),
        cadquery_timeout=cadquery_timeout,
    )

    if not is_solidworks_available():
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.warning(
            "sw.task.generate_sldprt_cadquery.unavailable",
            task_id=task_id,
            platform=_platform_info(),
        )
        return _degraded_result(
            task_id, task_name, "solidworks_unavailable",
            "pywin32 未安装或非 Windows 平台，无法生成 SLDPRT",
            elapsed_ms=elapsed_ms,
        )

    try:
        from app.services.solidworks import generate_sldprt_from_cadquery

        result_path = generate_sldprt_from_cadquery(
            code, Path(output_path), timeout=cadquery_timeout,
        )
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.info(
            "sw.task.generate_sldprt_cadquery.done",
            task_id=task_id,
            elapsed_ms=elapsed_ms,
            output_path=str(result_path),
        )
        return _success_result(
            task_id, task_name,
            result={"output_path": str(result_path)},
            elapsed_ms=elapsed_ms,
        )
    except (SolidWorksNotAvailableError, SolidWorksLicenseError) as e:
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.warning(
            "sw.task.generate_sldprt_cadquery.degraded",
            task_id=task_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return _degraded_result(
            task_id, task_name, type(e).__name__, str(e), elapsed_ms=elapsed_ms,
        )
    except (SolidWorksTaskTimeout, SolidWorksSessionError, SolidWorksTaskError) as e:
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.error(
            "sw.task.generate_sldprt_cadquery.error",
            task_id=task_id,
            error_type=type(e).__name__,
            error=str(e),
            elapsed_ms=elapsed_ms,
        )
        raise


# ===== 任务 4：generate_sldprt_from_features_task =====


@celery_app.task(
    name="app.celery.tasks.solidworks.generate_sldprt_from_features",
    bind=True,
    base=BaseTask,
    autoretry_for=(SolidWorksTaskTimeout, SolidWorksSessionError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=_MAX_RETRIES,
    acks_late=True,
    time_limit=_TASK_TIME_LIMIT,
    soft_time_limit=_TASK_SOFT_TIME_LIMIT,
)
def generate_sldprt_from_features_task(
    self: BaseTask,
    model_dict: dict[str, Any],
    output_path: str,
) -> dict[str, Any]:
    """从特征描述重建 SLDPRT（路径 B：FeatureManager API 逐个重建特征）。

    Args:
        model_dict: SolidWorksModel.model_dump() 序列化字典（含 features 列表）
        output_path: 输出 SLDPRT 文件路径

    Returns:
        标准结果 dict。``result`` 字段为 {"output_path": str, "warnings": list} 或 None。
    """
    task_id = self.request.id or "unknown"
    task_name = "generate_sldprt_from_features"
    t_start = time.perf_counter()
    log.info(
        "sw.task.generate_sldprt_features.start",
        task_id=task_id,
        output_path=output_path,
        features_count=len(model_dict.get("features", [])),
    )

    if not is_solidworks_available():
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.warning(
            "sw.task.generate_sldprt_features.unavailable",
            task_id=task_id,
            platform=_platform_info(),
        )
        return _degraded_result(
            task_id, task_name, "solidworks_unavailable",
            "pywin32 未安装或非 Windows 平台，无法生成 SLDPRT",
            elapsed_ms=elapsed_ms,
        )

    try:
        # 延迟导入：SolidWorksModel 用于反序列化校验
        from app.schemas.solidworks_model import SolidWorksModel
        from app.services.solidworks import generate_sldprt_from_features

        model = SolidWorksModel.model_validate(model_dict)
        result_path = generate_sldprt_from_features(model, Path(output_path))
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.info(
            "sw.task.generate_sldprt_features.done",
            task_id=task_id,
            elapsed_ms=elapsed_ms,
            output_path=str(result_path),
            warnings_count=len(model.warnings),
        )
        return _success_result(
            task_id, task_name,
            result={
                "output_path": str(result_path),
                "warnings": list(model.warnings),
            },
            elapsed_ms=elapsed_ms,
        )
    except (SolidWorksNotAvailableError, SolidWorksLicenseError) as e:
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.warning(
            "sw.task.generate_sldprt_features.degraded",
            task_id=task_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return _degraded_result(
            task_id, task_name, type(e).__name__, str(e), elapsed_ms=elapsed_ms,
        )
    except (SolidWorksTaskTimeout, SolidWorksSessionError, SolidWorksTaskError) as e:
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.error(
            "sw.task.generate_sldprt_features.error",
            task_id=task_id,
            error_type=type(e).__name__,
            error=str(e),
            elapsed_ms=elapsed_ms,
        )
        raise


# ===== 任务 5：generate_sldasm_from_components_task =====


@celery_app.task(
    name="app.celery.tasks.solidworks.generate_sldasm_from_components",
    bind=True,
    base=BaseTask,
    autoretry_for=(SolidWorksTaskTimeout, SolidWorksSessionError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=_MAX_RETRIES,
    acks_late=True,
    time_limit=_TASK_TIME_LIMIT,
    soft_time_limit=_TASK_SOFT_TIME_LIMIT,
)
def generate_sldasm_from_components_task(
    self: BaseTask,
    components: list[dict[str, Any]],
    output_path: str,
    mates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """从组件列表生成 SLDASM 装配体（路径 C：AddComponent5 + AddMate5）。

    Args:
        components: SWComponent.model_dump() 序列化字典列表
        output_path: 输出 SLDASM 文件路径
        mates: 可选，SWMate.model_dump() 序列化字典列表

    Returns:
        标准结果 dict。``result`` 字段为 {"output_path": str} 或 None。
    """
    task_id = self.request.id or "unknown"
    task_name = "generate_sldasm_from_components"
    t_start = time.perf_counter()
    log.info(
        "sw.task.generate_sldasm.start",
        task_id=task_id,
        output_path=output_path,
        components_count=len(components),
        mates_count=len(mates) if mates else 0,
    )

    if not is_solidworks_available():
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.warning(
            "sw.task.generate_sldasm.unavailable",
            task_id=task_id,
            platform=_platform_info(),
        )
        return _degraded_result(
            task_id, task_name, "solidworks_unavailable",
            "pywin32 未安装或非 Windows 平台，无法生成 SLDASM",
            elapsed_ms=elapsed_ms,
        )

    try:
        from app.schemas.solidworks_model import SWComponent, SWMate
        from app.services.solidworks import generate_sldasm_from_components

        # 反序列化校验（遵循"以瞎猜接口为耻"：不假设上游数据格式正确）
        comp_objs = [SWComponent.model_validate(c) for c in components]
        mate_objs = [SWMate.model_validate(m) for m in mates] if mates else None

        result_path = generate_sldasm_from_components(
            comp_objs, Path(output_path), mates=mate_objs,
        )
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.info(
            "sw.task.generate_sldasm.done",
            task_id=task_id,
            elapsed_ms=elapsed_ms,
            output_path=str(result_path),
        )
        return _success_result(
            task_id, task_name,
            result={"output_path": str(result_path)},
            elapsed_ms=elapsed_ms,
        )
    except (SolidWorksNotAvailableError, SolidWorksLicenseError) as e:
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.warning(
            "sw.task.generate_sldasm.degraded",
            task_id=task_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return _degraded_result(
            task_id, task_name, type(e).__name__, str(e), elapsed_ms=elapsed_ms,
        )
    except (SolidWorksTaskTimeout, SolidWorksSessionError, SolidWorksTaskError) as e:
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.error(
            "sw.task.generate_sldasm.error",
            task_id=task_id,
            error_type=type(e).__name__,
            error=str(e),
            elapsed_ms=elapsed_ms,
        )
        raise


# ===== 任务 6：license_status_task =====


@celery_app.task(
    name="app.celery.tasks.solidworks.license_status",
    bind=True,
    base=BaseTask,
    # 许可证查询不应重试（重试无意义，状态由 SolidWorks 决定）
    acks_late=True,
    time_limit=30,           # 轻量任务，30s 足够
    soft_time_limit=20,
)
def license_status_task(self: BaseTask, probe: bool = False) -> dict[str, Any]:
    """查询 SolidWorks 许可证状态（供 Linux AI 服务调度前探测）。

    跨平台降级：Linux/无 pywin32 时返回 ``status="unknown"``，不抛异常。

    Args:
        probe: 是否主动触发 Dispatch 探测（耗时 ~10s，准确）。
            默认 False，仅返回缓存的 ``last_status`` + ``is_available``（轻量，可能过期）。

    Returns:
        标准结果 dict。``result`` 字段为::

            {
                "status": "available" | "in_use" | "exhausted" | "unknown",
                "is_available": bool,           # 基于计数的快速判断
                "current_usage": int,           # 已获取的许可证数
                "max_licenses": int,            # 许可证上限
                "last_probe_time": float | None,  # 上次探测时间戳（monotonic）
                "platform": str,                # 平台信息
            }
    """
    task_id = self.request.id or "unknown"
    task_name = "license_status"
    t_start = time.perf_counter()
    log.info(
        "sw.task.license_status.start",
        task_id=task_id,
        probe=probe,
        platform=_platform_info(),
    )

    if not is_solidworks_available():
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        # 跨平台降级：返回 UNKNOWN 状态，不抛异常
        result = {
            "status": "unknown",
            "is_available": False,
            "current_usage": 0,
            "max_licenses": 0,
            "last_probe_time": None,
            "platform": _platform_info(),
        }
        log.info(
            "sw.task.license_status.degraded",
            task_id=task_id,
            elapsed_ms=elapsed_ms,
        )
        return _success_result(task_id, task_name, result, elapsed_ms=elapsed_ms)

    try:
        from app.services.solidworks.license import get_license_manager

        mgr = get_license_manager(max_licenses=1)
        if probe:
            status = mgr.get_status()  # 主动探测（耗时 ~10s）
        else:
            status = mgr.last_status  # 缓存状态（轻量）

        result = {
            "status": status.value,
            "is_available": mgr.is_available,
            "current_usage": mgr.current_usage,
            "max_licenses": mgr.max_licenses,
            "last_probe_time": mgr.last_probe_time,
            "platform": _platform_info(),
        }
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.info(
            "sw.task.license_status.done",
            task_id=task_id,
            elapsed_ms=elapsed_ms,
            status=status.value,
            usage=mgr.current_usage,
            max=mgr.max_licenses,
            probe=probe,
        )
        return _success_result(task_id, task_name, result, elapsed_ms=elapsed_ms)
    except Exception as e:  # noqa: BLE001
        # 兜底：任何异常都返回降级结果，避免任务失败影响 AI 服务调度
        elapsed_ms = int((time.perf_counter() - t_start) * 1000)
        log.warning(
            "sw.task.license_status.error",
            task_id=task_id,
            error_type=type(e).__name__,
            error=str(e),
            elapsed_ms=elapsed_ms,
        )
        return _degraded_result(
            task_id, task_name, "license_query_failed", str(e),
            elapsed_ms=elapsed_ms,
        )


# ===== 工具函数 =====


def _platform_info() -> str:
    """返回平台信息字符串（用于日志与降级结果）。"""
    import platform

    return f"{platform.system()}/{platform.machine()}"


# ===== SubTask 17.1: Worker 启动时预热 SolidWorks 池 =====


def _on_solidworks_worker_ready(sender: Any = None, **kwargs: Any) -> None:
    """worker_ready 信号钩子：在 SolidWorks Worker 启动时预热池。

    遵循"以谨慎重构为荣"原则：
    - 仅在 solidworks 队列的 worker 上触发预热（避免 Linux AI 服务 worker 误触发）
    - 读 settings.SOLIDWORKS_PREWARM_COUNT 决定预热数量（默认 0=不预热）
    - 任何异常都只记日志不抛出（不阻塞 worker 启动）
    """
    try:
        from app.config import settings
        from app.services.solidworks.worker_pool import prewarm_pool

        count = int(getattr(settings, "SOLIDWORKS_PREWARM_COUNT", 0))
        if count <= 0:
            log.info(
                "sw.worker.prewarm_disabled",
                reason="SOLIDWORKS_PREWARM_COUNT <= 0",
                count=count,
            )
            return
        result = prewarm_pool(count=count)
        log.info(
            "sw.worker.prewarm_result",
            status=result.get("status"),
            count=result.get("count"),
            reason=result.get("reason"),
            session_started=result.get("session_started"),
            health=result.get("health_status"),
        )
    except Exception as e:  # noqa: BLE001
        # 预热失败不阻塞 worker 启动
        log.warning(
            "sw.worker.prewarm_hook_error",
            error=str(e),
            error_type=type(e).__name__,
        )


try:
    from celery.signals import worker_ready

    worker_ready.connect(_on_solidworks_worker_ready)
except ImportError:  # pragma: no cover
    pass


# ===== 离线自检 =====


def _self_test() -> dict[str, Any]:
    """离线自检：验证 Celery solidworks 任务模块完整性。

    本函数不调用 SolidWorks API、不连接 Redis，可在 Linux 环境运行。
    用于 CI / 离线环境验证模块可导入性与任务注册完整性。

    Returns:
        {"ok": bool, "errors": list[str], "checks": dict[str, bool]}
    """
    checks: dict[str, bool] = {}
    errors: list[str] = []

    # 1. 模块导入安全（Linux/无 pywin32 下也应成功）
    try:
        # 触发本模块的所有顶层导入（包括 celery_app、solidworks 包等）
        checks["module_import"] = True
        checks["is_solidworks_available_bool"] = isinstance(
            is_solidworks_available(), bool
        )
    except Exception as e:  # noqa: BLE001
        checks["module_import"] = False
        errors.append(f"模块导入失败: {e}")

    # 2. 6 个 Celery 任务均已被 celery_app 注册
    try:
        expected_task_names = {
            "app.celery.tasks.solidworks.read_sldprt",
            "app.celery.tasks.solidworks.read_sldasm",
            "app.celery.tasks.solidworks.generate_sldprt_from_cadquery",
            "app.celery.tasks.solidworks.generate_sldprt_from_features",
            "app.celery.tasks.solidworks.generate_sldasm_from_components",
            "app.celery.tasks.solidworks.license_status",
        }
        # celery_app.tasks 是 TaskRegistry，包含所有已注册任务名
        registered = set(celery_app.tasks.keys())
        missing = expected_task_names - registered
        checks["all_tasks_registered"] = len(missing) == 0
        if missing:
            errors.append(f"未注册的任务: {missing}")
        # 验证任务数量为 6
        checks["tasks_count_is_6"] = len(expected_task_names) == 6
    except Exception as e:  # noqa: BLE001
        checks["all_tasks_registered"] = False
        errors.append(f"任务注册校验失败: {e}")

    # 3. 任务可调用（装饰器未破坏函数可调用性）
    try:
        checks["read_sldprt_task_callable"] = callable(read_sldprt_task)
        checks["read_sldasm_task_callable"] = callable(read_sldasm_task)
        checks["generate_sldprt_from_cadquery_task_callable"] = callable(
            generate_sldprt_from_cadquery_task
        )
        checks["generate_sldprt_from_features_task_callable"] = callable(
            generate_sldprt_from_features_task
        )
        checks["generate_sldasm_from_components_task_callable"] = callable(
            generate_sldasm_from_components_task
        )
        checks["license_status_task_callable"] = callable(license_status_task)
    except Exception as e:  # noqa: BLE001
        checks["tasks_callable"] = False
        errors.append(f"任务可调用性校验失败: {e}")

    # 4. 任务配置（time_limit / acks_late）合规
    try:
        # 通过任务对象的属性验证配置
        t = read_sldprt_task
        # Celery Task 对象暴露 time_limit / soft_time_limit 属性
        checks["task_time_limit_300"] = getattr(t, "time_limit", None) == 300
        checks["task_soft_time_limit_270"] = (
            getattr(t, "soft_time_limit", None) == 270
        )
        checks["task_acks_late"] = getattr(t, "acks_late", False) is True
        # license_status_task 时间限制应更短（30s）
        lt = license_status_task
        checks["license_task_time_limit_30"] = (
            getattr(lt, "time_limit", None) == 30
        )
    except Exception as e:  # noqa: BLE001
        checks["task_config"] = False
        errors.append(f"任务配置校验失败: {e}")

    # 5. 工具函数可调用
    try:
        checks["degraded_result_callable"] = callable(_degraded_result)
        checks["success_result_callable"] = callable(_success_result)
        checks["platform_info_callable"] = callable(_platform_info)
        # 验证 _degraded_result 返回结构
        r = _degraded_result("t1", "tn", "test_reason", "test_msg", elapsed_ms=10)
        checks["degraded_result_schema"] = (
            r["success"] is False
            and r["error"] == "test_reason"
            and r["message"] == "test_msg"
            and r["task_id"] == "t1"
            and r["elapsed_ms"] == 10
            and r["result"] is None
        )
        # 验证 _success_result 返回结构
        s = _success_result("t1", "tn", {"key": "val"}, elapsed_ms=20)
        checks["success_result_schema"] = (
            s["success"] is True
            and s["error"] is None
            and s["result"] == {"key": "val"}
            and s["elapsed_ms"] == 20
        )
        # _platform_info 返回非空字符串
        checks["platform_info_str"] = isinstance(_platform_info(), str) and len(_platform_info()) > 0
    except Exception as e:  # noqa: BLE001
        checks["util_functions"] = False
        errors.append(f"工具函数校验失败: {e}")

    # 6. 跨平台降级行为（通过模拟无 pywin32 验证任务不抛异常）
    try:
        # 通过 patch is_solidworks_available 模拟 Linux 环境
        import app.celery.tasks.solidworks as sw_tasks_mod

        original_avail = sw_tasks_mod.is_solidworks_available
        sw_tasks_mod.is_solidworks_available = lambda: False  # type: ignore
        try:
            # 模拟 BaseTask.request.id（license_status_task 不依赖 self.request.id 之外的属性）
            # 通过 .run 调用底层函数体（绕过 Celery 调度）
            # 注意：直接调用 __call__ 会触发 Celery 调度，这里用 .run 方法
            # license_status_task.run(probe=False) 不依赖 self.request.id（会用 "unknown"）
            result = license_status_task.run(probe=False)
            checks["degraded_license_status_no_raise"] = isinstance(result, dict)
            checks["degraded_license_status_success_true"] = (
                result.get("success") is True  # 任务本身成功，但 result.status="unknown"
            )
            checks["degraded_license_status_unknown"] = (
                result.get("result", {}).get("status") == "unknown"
            )
        finally:
            sw_tasks_mod.is_solidworks_available = original_avail  # type: ignore
    except Exception as e:  # noqa: BLE001
        checks["degraded_behavior"] = False
        errors.append(f"跨平台降级行为校验失败: {e}")

    ok = all(checks.values()) if checks else False
    return {"ok": ok, "errors": errors, "checks": checks}


__all__ = [
    "read_sldprt_task",
    "read_sldasm_task",
    "generate_sldprt_from_cadquery_task",
    "generate_sldprt_from_features_task",
    "generate_sldasm_from_components_task",
    "license_status_task",
    "_self_test",
]


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys

    result = _self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["ok"] else 1)
