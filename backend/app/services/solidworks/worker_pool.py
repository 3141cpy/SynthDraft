"""SolidWorks Worker 池（SubTask 7.1 + 7.4）。

设计原则（spec.md §"系统架构设计" 架构原则 §1）：
- AI 服务无状态、SolidWorks Worker 有状态
- SolidWorks 必须运行在装有其许可证的 Windows 机器上
- Worker Pool 池化复用，避免每次启动开销（Dispatch 启动 ~10s）

本模块实现 SubTask 7.1 的进程内 Worker 池：
- 基于 SolidWorksSession 单例（避免重复 Dispatch）
- 任务串行执行（SolidWorks COM 是 STA，多线程访问需串行化）
- 任务超时保护（hard timeout + 软中断）
- 健康检查（ping SolidWorks 实例，crash 后自动重启）
- 进程隔离（每个 Celery worker 进程独立 SolidWorksSession 单例）

SubTask 7.4 扩展（本版本）：
- 任务超时强制 kill SolidWorks 进程并重启（_kill_solidworks_process）
- 进程隔离增强（max_concurrent_sessions + Semaphore + acquire_slot/release_slot）
- 健康检查分级（HealthStatus 枚举：healthy/degraded/unhealthy/restarting/stopped）
- 自动重启增强（_restart_with_retry 指数退避 + on_restart 回调 + restart_count）
- 任务注册表（_task_registry：task_id → thread/start_time/timeout）
- is_busy / wait_for_idle 用于优雅关闭与并发控制

SubTask 7.5 已实施：
- Celery solidworks 队列（见 app/celery/tasks/solidworks.py）
- Linux AI 服务通过 Celery 投递任务到 Windows Worker

SubTask 7.6 已实施（本版本）：
- SolidWorks 许可证计数（SolidWorksLicenseManager，max_licenses 限制并发实例）
- start() 前调用 license_manager.acquire()，超限抛 SolidWorksLicenseError
- shutdown() 后调用 license_manager.release()
- license_status / max_licenses 属性暴露许可证状态
"""

from __future__ import annotations

import functools
import subprocess
import threading
import time
from typing import Any, Callable, TypeVar

from app.logging import get_logger
from app.services.solidworks.exceptions import (
    SolidWorksLicenseError,
    SolidWorksSessionError,
    SolidWorksTaskError,
    SolidWorksTaskTimeout,
)
from app.services.solidworks.license import (
    LicenseStatus,
    SolidWorksLicenseManager,
)
from app.services.solidworks.status import HealthStatus
from app.services.solidworks.sw_session import (
    SolidWorksSession,
    get_session,
    is_solidworks_available,
)

log = get_logger(__name__)

T = TypeVar("T")

# Windows 进程终止访问权限常量（PROCESS_TERMINATE = 0x0001）
# 来源：Win32 API winnt.h，pywin32 win32con.PROCESS_TERMINATE 同值
_PROCESS_TERMINATE = 0x0001


class SolidWorksWorkerPool:
    """SolidWorks Worker 池（进程内单例）。

    用法：
        pool = SolidWorksWorkerPool(max_workers=1)
        pool.start()  # 启动 SolidWorksSession
        result = pool.submit(my_task_fn, arg1, arg2, timeout=60)
        pool.shutdown()

    注意：
    - max_workers=1 推荐（SolidWorks 许可证通常限制并发实例数）
    - 任务串行执行（SolidWorks COM 是 STA）
    - submit 的 timeout 是硬超时（超时后任务被取消，会话可能需重启）

    SubTask 7.4 新增：
    - max_concurrent_sessions：并发槽位数（默认 1，对应许可证限制）
    - acquire_slot / release_slot：基于 Semaphore 的并发控制
    - is_busy / wait_for_idle：状态查询与等待
    - health_status：分级健康状态（HealthStatus 枚举）
    - _kill_solidworks_process：超时后强制 kill SW 进程
    - _restart_with_retry：指数退避重启重试
    - on_restart 回调：重启后通知调用方
    """

    _instance: "SolidWorksWorkerPool | None" = None
    _singleton_lock = threading.Lock()

    def __new__(
        cls,
        max_workers: int = 1,
        max_concurrent_sessions: int = 1,
    ) -> "SolidWorksWorkerPool":
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._initialized = False  # type: ignore[attr-defined]
                    inst._max_workers = max_workers  # type: ignore[attr-defined]
                    inst._max_concurrent_sessions = max(  # type: ignore[attr-defined]
                        1, max_concurrent_sessions
                    )
                    cls._instance = inst
        return cls._instance

    def __init__(
        self,
        max_workers: int = 1,
        max_concurrent_sessions: int = 1,
    ) -> None:
        if getattr(self, "_initialized", False):
            return
        if not is_solidworks_available():
            log.warning(
                "sw.worker_pool.unavailable",
                reason="pywin32 not installed or non-Windows platform",
            )
        # 延迟初始化：Linux/无 pywin32 时 get_session() 会抛异常，
        # 此处用 try/except 包裹，实际 session 在 start() 中按需创建
        try:
            self._session: SolidWorksSession | None = get_session()
        except Exception:
            self._session = None
        # COM STA 线程亲和性：记录创建 session 的线程，submit 时同线程直接执行
        self._session_thread: threading.Thread | None = None
        self._max_workers = max(1, max_workers)
        # 并发槽位（SubTask 7.4）：默认 1，对应 SolidWorks 许可证限制
        self._max_concurrent_sessions = max(1, max_concurrent_sessions)
        self._session_semaphore = threading.Semaphore(self._max_concurrent_sessions)
        # 任务串行执行锁（SolidWorks COM 是 STA）—— 保留用于内部串行化
        self._exec_lock = threading.Lock()
        # 空闲事件（SubTask 7.4）：用于 wait_for_idle
        self._idle_event = threading.Event()
        self._idle_event.set()  # 初始空闲
        # 任务运行中标记（SubTask 7.4）
        self._busy = False
        self._busy_lock = threading.Lock()
        # 健康检查定时器
        self._health_check_interval = 60.0  # 秒
        self._health_check_timer: threading.Timer | None = None
        self._health_check_running = False
        # 任务计数（用于监控）
        self._task_count = 0
        self._task_failed_count = 0
        # 任务注册表（SubTask 7.4）：task_id → {thread, start_time, timeout}
        self._task_registry: dict[int, dict[str, Any]] = {}
        self._task_registry_lock = threading.Lock()
        # 健康状态（SubTask 7.4）
        self._health_status: HealthStatus = HealthStatus.STOPPED
        self._consecutive_failures = 0
        self._max_consecutive_failures = 3  # 连续失败阈值触发硬重启
        self._last_health_check_time: float | None = None
        self._last_healthy_time: float | None = None
        # 重启监控（SubTask 7.4）
        self._restart_count = 0
        self._last_restart_reason: str | None = None
        self._on_restart_callbacks: list[Callable[[str], None]] = []
        self._restart_lock = threading.Lock()  # 防止并发重启
        # 许可证管理（SubTask 7.6）：max_licenses 与 max_workers 对齐
        self._license_manager: SolidWorksLicenseManager = SolidWorksLicenseManager(
            max_licenses=self._max_workers
        )
        self._license_acquired = False  # 标记是否已获取许可证（用于 shutdown 释放）
        self._initialized = True

    # ===== 基础属性 =====

    @property
    def max_workers(self) -> int:
        """最大 Worker 数（SolidWorks 实例数）。"""
        return self._max_workers

    @property
    def max_concurrent_sessions(self) -> int:
        """最大并发会话槽位数（SubTask 7.4）。

        默认 1，对应 SolidWorks 许可证通常限制并发实例数。
        通过 acquire_slot / release_slot 控制。
        """
        return self._max_concurrent_sessions

    @property
    def task_count(self) -> int:
        """累计任务数。"""
        return self._task_count

    @property
    def task_failed_count(self) -> int:
        """累计失败任务数。"""
        return self._task_failed_count

    @property
    def session_started(self) -> bool:
        """SolidWorks 会话是否已启动。"""
        return self._session is not None and self._session.started

    # ===== SubTask 7.6：许可证管理属性 =====

    @property
    def license_status(self) -> LicenseStatus:
        """当前许可证状态（SubTask 7.6）。

        返回上次探测的状态（不触发 Dispatch 探测）。
        如需主动探测，调用 ``self._license_manager.get_status()``。
        """
        return self._license_manager.last_status

    @property
    def max_licenses(self) -> int:
        """许可证上限（SubTask 7.6，与 max_workers 对齐）。"""
        return self._license_manager.max_licenses

    @property
    def license_manager(self) -> SolidWorksLicenseManager:
        """内部许可证管理器实例（SubTask 7.6）。

        暴露内部组件以便高级用法（如主动探测、健康检查集成）。
        """
        return self._license_manager

    # ===== SubTask 7.4：进程隔离与并发控制 =====

    @property
    def is_busy(self) -> bool:
        """当前是否有任务运行中（SubTask 7.4）。

        用于优雅关闭前等待任务完成（wait_for_idle）。
        """
        return self._busy

    def acquire_slot(self, timeout: float | None = None) -> bool:
        """获取并发槽位（SubTask 7.4）。

        基于 threading.Semaphore 控制并发，槽位数由 max_concurrent_sessions 决定。
        默认 1，确保 SolidWorks COM STA 串行访问。

        Args:
            timeout: 等待超时（秒），None 表示无限等待

        Returns:
            True 表示获取成功；False 表示超时
        """
        if timeout is None:
            self._session_semaphore.acquire()
            return True
        return self._session_semaphore.acquire(timeout=timeout)

    def release_slot(self) -> None:
        """释放并发槽位（SubTask 7.4）。"""
        self._session_semaphore.release()

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        """等待 Worker 空闲（SubTask 7.4）。

        用于优雅关闭前等待当前任务完成。

        Args:
            timeout: 等待超时（秒），None 表示无限等待

        Returns:
            True 表示已空闲；False 表示超时
        """
        if timeout is None:
            self._idle_event.wait()
            return True
        return self._idle_event.wait(timeout=timeout)

    def _mark_busy(self) -> None:
        """标记 Worker 忙碌（内部方法）。"""
        with self._busy_lock:
            self._busy = True
            self._idle_event.clear()

    def _mark_idle(self) -> None:
        """标记 Worker 空闲（内部方法）。"""
        with self._busy_lock:
            self._busy = False
            self._idle_event.set()

    # ===== SubTask 7.4：健康状态 =====

    @property
    def health_status(self) -> HealthStatus:
        """Worker Pool 当前健康状态（SubTask 7.4）。"""
        return self._health_status

    @property
    def consecutive_failures(self) -> int:
        """连续健康检查失败次数（SubTask 7.4）。"""
        return self._consecutive_failures

    @property
    def last_health_check_time(self) -> float | None:
        """上次健康检查时间戳（monotonic，SubTask 7.4）。"""
        return self._last_health_check_time

    @property
    def last_healthy_time(self) -> float | None:
        """上次健康时间戳（monotonic，SubTask 7.4）。"""
        return self._last_healthy_time

    # ===== SubTask 7.4：重启监控 =====

    @property
    def restart_count(self) -> int:
        """累计重启次数（SubTask 7.4）。"""
        return self._restart_count

    @property
    def last_restart_reason(self) -> str | None:
        """上次重启原因（SubTask 7.4）。"""
        return self._last_restart_reason

    def register_on_restart(self, callback: Callable[[str], None]) -> None:
        """注册重启回调（SubTask 7.4）。

        重启成功后调用所有回调，传入重启原因。
        用于调用方重试失败任务。

        Args:
            callback: 回调函数，签名 fn(reason: str) -> None
        """
        self._on_restart_callbacks.append(callback)

    def _notify_restart(self, reason: str) -> None:
        """通知所有重启回调（内部方法）。"""
        for cb in self._on_restart_callbacks:
            try:
                cb(reason)
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "sw.worker_pool.restart_callback_failed",
                    error=str(e),
                    reason=reason,
                )

    def _set_health_status(self, status: HealthStatus) -> None:
        """更新健康状态并记录日志（内部方法）。"""
        old = self._health_status
        self._health_status = status
        if old != status:
            log.info(
                "sw.worker_pool.health_status_changed",
                old=old.value,
                new=status.value,
            )

    # ===== 生命周期管理 =====

    def start(self, visible: bool = False) -> None:
        """启动 Worker 池（初始化 SolidWorksSession）。

        Args:
            visible: 是否显示 SolidWorks GUI

        Raises:
            SolidWorksNotAvailableError: pywin32 未安装或非 Windows 平台
            SolidWorksLicenseError: 许可证不可用或并发已满（SubTask 7.6）
        """
        if not is_solidworks_available():
            from app.services.solidworks.exceptions import (
                SolidWorksNotAvailableError,
            )

            raise SolidWorksNotAvailableError(
                "pywin32 未安装或非 Windows 平台，无法启动 SolidWorks Worker Pool"
            )
        # SubTask 7.6：启动前获取许可证槽位（计数前置校验）
        if not self._license_manager.acquire():
            raise SolidWorksLicenseError(
                f"SolidWorks 许可证不可用或并发已满 "
                f"(usage={self._license_manager.current_usage}/"
                f"max={self._license_manager.max_licenses})"
            )
        self._license_acquired = True
        try:
            # 延迟初始化 session（__init__ 中 get_session() 可能失败）
            if self._session is None:
                self._session = get_session()
            self._session.start(visible=visible)
            # 记录创建 COM session 的线程（COM STA 线程亲和性）
            self._session_thread = threading.current_thread()
        except Exception:
            # 会话启动失败：释放许可证槽位，避免计数泄漏
            self._license_manager.release()
            self._license_acquired = False
            raise
        self._consecutive_failures = 0
        self._last_healthy_time = time.monotonic()
        self._set_health_status(HealthStatus.HEALTHY)
        self._start_health_check()
        log.info(
            "sw.worker_pool.started",
            revision=self._session.revision,
            max_workers=self._max_workers,
            max_concurrent_sessions=self._max_concurrent_sessions,
            max_licenses=self._license_manager.max_licenses,
        )

    def shutdown(self) -> None:
        """关闭 Worker 池（退出 SolidWorks 实例）。"""
        self._stop_health_check()
        if self._session is not None:
            self._session.close()
        self._set_health_status(HealthStatus.STOPPED)
        # SubTask 7.6：释放许可证槽位（仅在曾获取时释放，避免计数下溢）
        if self._license_acquired:
            self._license_manager.release()
            self._license_acquired = False
        log.info(
            "sw.worker_pool.shutdown",
            task_count=self._task_count,
            task_failed=self._task_failed_count,
            restart_count=self._restart_count,
            license_usage=self._license_manager.current_usage,
        )

    def submit(
        self,
        task_fn: Callable[..., T],
        *args: Any,
        timeout: float = 60.0,
        **kwargs: Any,
    ) -> T:
        """提交任务到 Worker 池（同步执行）。

        Args:
            task_fn: 任务函数（签名：fn(session: SolidWorksSession, *args, **kwargs)）
            *args: 任务参数
            timeout: 硬超时（秒），超时抛 SolidWorksTaskTimeout
            **kwargs: 任务关键字参数

        Returns:
            任务返回值

        Raises:
            SolidWorksTaskTimeout: 任务超时
            SolidWorksTaskError: 任务执行失败
            SolidWorksSessionError: 会话异常
        """
        if self._session is None or not self._session.started:
            raise SolidWorksSessionError(
                "Worker Pool 未启动，请先调用 start()"
            )

        # 健康检查：会话崩溃则重启
        if not self._session.ping():
            log.warning("sw.worker_pool.session_unhealthy_restart")
            self._restart_with_retry(reason="pre_submit_ping_failed")

        self._task_count += 1
        task_id = self._task_count
        log.info(
            "sw.worker_pool.task_submitted",
            task_id=task_id,
            task_fn=task_fn.__name__,
            timeout=timeout,
        )

        # 获取并发槽位（SubTask 7.4）
        if not self.acquire_slot(timeout=timeout):
            self._task_failed_count += 1
            raise SolidWorksTaskTimeout(
                f"任务 {task_fn.__name__} (task_id={task_id}) "
                f"等待并发槽位超时 ({timeout}s)"
            )

        self._mark_busy()

        # COM STA 线程亲和性快速路径：若当前线程即创建 session 的线程，
        # 直接执行任务，避免跨线程 COM 调用触发 RPC_E_WRONG_THREAD (0x8001010E)。
        # SolidWorks COM 是 STA，OpenDoc6 等方法调用必须在与 Dispatch 相同的线程执行。
        if (
            self._session_thread is not None
            and threading.current_thread() is self._session_thread
        ):
            start_time = time.monotonic()
            with self._task_registry_lock:
                self._task_registry[task_id] = {
                    "thread": None,
                    "start_time": start_time,
                    "timeout": timeout,
                    "task_fn": task_fn.__name__,
                }
            try:
                with self._exec_lock:
                    try:
                        result = task_fn(self._session, *args, **kwargs)
                    except Exception as e:
                        self._task_failed_count += 1
                        elapsed = time.monotonic() - start_time
                        log.error(
                            "sw.worker_pool.task_failed",
                            task_id=task_id,
                            error=str(e),
                            elapsed=elapsed,
                        )
                        if isinstance(
                            e,
                            (
                                SolidWorksTaskError,
                                SolidWorksSessionError,
                                SolidWorksLicenseError,
                            ),
                        ):
                            raise e
                        raise SolidWorksTaskError(
                            f"任务 {task_fn.__name__} (task_id={task_id}) "
                            f"执行失败：{e}"
                        ) from e
                elapsed = time.monotonic() - start_time
                log.info(
                    "sw.worker_pool.task_completed",
                    task_id=task_id,
                    elapsed=elapsed,
                    same_thread=True,
                )
                return result
            finally:
                with self._task_registry_lock:
                    self._task_registry.pop(task_id, None)
                self._mark_idle()
                self.release_slot()

        result_box: dict[str, Any] = {}

        def _run() -> None:
            # Windows COM STA 线程必须初始化 COM（SolidWorks COM 是 STA）
            _co_initialized = False
            try:
                import sys as _sys
                if _sys.platform == "win32":
                    import pythoncom as _pythoncom
                    _pythoncom.CoInitialize()
                    _co_initialized = True
            except ImportError:
                pass

            try:
                with self._exec_lock:
                    try:
                        result_box["value"] = task_fn(self._session, *args, **kwargs)
                    except Exception as e:  # noqa: BLE001
                        result_box["error"] = e
            finally:
                if _co_initialized:
                    try:
                        _pythoncom.CoUninitialize()
                    except Exception:  # noqa: BLE001
                        pass

        thread = threading.Thread(target=_run, daemon=True)
        start_time = time.monotonic()

        # 注册任务（SubTask 7.4）
        with self._task_registry_lock:
            self._task_registry[task_id] = {
                "thread": thread,
                "start_time": start_time,
                "timeout": timeout,
                "task_fn": task_fn.__name__,
            }

        thread.start()
        thread.join(timeout=timeout)
        elapsed = time.monotonic() - start_time

        try:
            if thread.is_alive():
                # 超时：线程仍在运行（SubTask 7.4 增强：强制 kill SW 进程并重启）
                self._task_failed_count += 1
                log.error(
                    "sw.worker_pool.task_timeout",
                    task_id=task_id,
                    timeout=timeout,
                    elapsed=elapsed,
                )
                # 强制 kill SolidWorks 进程（终止卡住的 COM 调用）
                killed = self._kill_solidworks_process(
                    reason=f"task_timeout_{task_id}"
                )
                # 等待线程退出（kill 后 COM 调用应快速失败）
                thread.join(timeout=5.0)
                if thread.is_alive():
                    log.warning(
                        "sw.worker_pool.thread_still_alive_after_kill",
                        task_id=task_id,
                        killed=killed,
                    )
                # 重启会话恢复可用性
                try:
                    self._restart_with_retry(
                        reason=f"task_timeout_{task_id}"
                    )
                except SolidWorksSessionError as e:
                    log.error(
                        "sw.worker_pool.restart_after_timeout_failed",
                        task_id=task_id,
                        error=str(e),
                    )
                raise SolidWorksTaskTimeout(
                    f"任务 {task_fn.__name__} (task_id={task_id}) 超时 "
                    f"({elapsed:.1f}s > {timeout}s)，已 kill SW 进程并重启"
                )

            if "error" in result_box:
                self._task_failed_count += 1
                err = result_box["error"]
                log.error(
                    "sw.worker_pool.task_failed",
                    task_id=task_id,
                    error=str(err),
                    elapsed=elapsed,
                )
                if isinstance(err, (
                    SolidWorksTaskError,
                    SolidWorksSessionError,
                    SolidWorksLicenseError,
                )):
                    raise err
                raise SolidWorksTaskError(
                    f"任务 {task_fn.__name__} (task_id={task_id}) 执行失败：{err}"
                ) from err

            log.info(
                "sw.worker_pool.task_completed",
                task_id=task_id,
                elapsed=elapsed,
            )
            return result_box["value"]  # type: ignore[no-any-return]
        finally:
            # 清理任务注册表
            with self._task_registry_lock:
                self._task_registry.pop(task_id, None)
            # 释放并发槽位与忙碌标记
            self._mark_idle()
            self.release_slot()

    def health_check(self) -> bool:
        """健康检查：验证 SolidWorks 实例存活（SubTask 7.4 增强）。

        副作用：更新 _health_status / _consecutive_failures / 时间戳。
        连续失败达 _max_consecutive_failures 时由 _check_loop 触发硬重启。

        Returns:
            True 表示健康；False 表示需重启
        """
        self._last_health_check_time = time.monotonic()
        if self._session is None or not self._session.started:
            self._set_health_status(HealthStatus.STOPPED)
            return False

        healthy = self._session.ping()
        if healthy:
            self._consecutive_failures = 0
            self._last_healthy_time = self._last_health_check_time
            self._set_health_status(HealthStatus.HEALTHY)
            return True

        # ping 失败：区分 degraded / unhealthy
        self._consecutive_failures += 1
        # 会话对象仍存在但 ping 失败 → degraded
        if self._session._sw_app is not None:  # type: ignore[attr-defined]
            self._set_health_status(HealthStatus.DEGRADED)
        else:
            self._set_health_status(HealthStatus.UNHEALTHY)
        log.warning(
            "sw.worker_pool.health_check_failed",
            consecutive_failures=self._consecutive_failures,
            status=self._health_status.value,
        )
        return False

    def restart(self) -> None:
        """重启 SolidWorks 会话（崩溃恢复，SubTask 7.4 委托给带重试的版本）。"""
        self._restart_with_retry(reason="explicit_restart")

    # ===== SubTask 17.1: Worker 池预热 =====

    def prewarm_pool(self, count: int = 1) -> dict[str, Any]:
        """预热 Worker 池（SubTask 17.1）。

        启动时预先创建 SolidWorks 进程，避免首次任务等待 Dispatch 启动开销（~10s）。
        本方法为幂等操作：
        - count <= 0：无副作用，直接返回 skipped
        - 已预热（session_started=True）：返回 already_started
        - SolidWorks 不可用 / 许可证不可用：优雅降级，返回 degraded（不抛异常）
        - 预热成功：返回 ok

        实际仅启动 1 个 SolidWorks 实例（max_workers=1，受许可证限制），
        count 参数主要用于配置开关与未来扩展。

        Args:
            count: 预热数量（建议 0 或 1；>1 时仍只启动 1 个实例）

        Returns:
            {
                "status": "ok" | "skipped" | "already_started" | "degraded",
                "count": int,
                "reason": str,
                "session_started": bool,
                "health_status": str,
            }
        """
        # count <= 0：无副作用
        if count <= 0:
            log.info("sw.worker_pool.prewarm_skipped", count=count, reason="count_le_zero")
            return {
                "status": "skipped",
                "count": count,
                "reason": "count <= 0, no prewarm",
                "session_started": self.session_started,
                "health_status": self._health_status.value,
            }

        # 已启动：幂等返回
        if self.session_started:
            log.info(
                "sw.worker_pool.prewarm_already_started",
                count=count,
                health=self._health_status.value,
            )
            return {
                "status": "already_started",
                "count": count,
                "reason": "session already started",
                "session_started": True,
                "health_status": self._health_status.value,
            }

        # 平台不可用：优雅降级
        if not is_solidworks_available():
            log.warning(
                "sw.worker_pool.prewarm_degraded",
                count=count,
                reason="solidworks_unavailable",
            )
            return {
                "status": "degraded",
                "count": count,
                "reason": "pywin32 未安装或非 Windows 平台",
                "session_started": False,
                "health_status": self._health_status.value,
            }

        # 尝试启动（许可证不可用时优雅降级）
        try:
            self.start(visible=False)
            log.info(
                "sw.worker_pool.prewarm_ok",
                count=count,
                revision=self._session.revision,
                health=self._health_status.value,
            )
            return {
                "status": "ok",
                "count": count,
                "reason": "prewarm completed",
                "session_started": True,
                "health_status": self._health_status.value,
            }
        except Exception as e:  # noqa: BLE001
            # 许可证不可用 / Dispatch 失败等：优雅降级，不抛异常
            log.warning(
                "sw.worker_pool.prewarm_failed",
                count=count,
                error=str(e),
                error_type=type(e).__name__,
            )
            return {
                "status": "degraded",
                "count": count,
                "reason": f"prewarm failed: {type(e).__name__}: {e}",
                "session_started": self.session_started,
                "health_status": self._health_status.value,
            }

    # ===== SubTask 7.4：进程 kill =====

    def _kill_solidworks_process(self, reason: str = "") -> bool:
        """强制 kill SolidWorks 进程（SubTask 7.4）。

        超时后调用，终止卡住的 COM 调用。
        多策略降级（所有策略用 try/except 包裹，失败仅记日志不抛异常）：
          1. 尝试 sw_app.GetProcessId() 获取 PID（存疑 API，可能不存在）
          2. 若 pywin32 可用：win32api.OpenProcess + TerminateProcess + CloseHandle
          3. 降级：os.system / subprocess 调用 taskkill /F /PID {pid}
          4. 最终降级：taskkill /F /IM sldworks.exe（按映像名 kill，无需 PID）

        跨平台：Linux/无 pywin32 时仅记日志，kill 不可用（无副作用）。

        Args:
            reason: kill 原因（用于日志）

        Returns:
            True 表示 kill 成功（或已确认进程不存在）；False 表示 kill 失败
        """
        sw_app = getattr(self._session, "_sw_app", None)
        if sw_app is None:
            log.info(
                "sw.worker_pool.kill_noop",
                reason=reason,
                detail="session._sw_app is None, no process to kill",
            )
            return True

        # 策略 1：尝试获取 PID（存疑 API，GetProcessId 在 SldWorks.Application 上
        # 无官方文档确认，可能不存在或返回不同类型）
        pid: int | None = None
        try:
            for attr in ("GetProcessId", "ProcessId", "ProcessID"):
                getter = getattr(sw_app, attr, None)
                if getter is None:
                    continue
                val = getter() if callable(getter) else getter
                if isinstance(val, int) and val > 0:
                    pid = val
                    break
        except Exception as e:  # noqa: BLE001
            log.debug(
                "sw.worker_pool.get_pid_failed",
                reason=reason,
                error=str(e),
            )

        killed = False

        # 策略 2：pywin32 OpenProcess + TerminateProcess
        # API 参考：https://github.com/mhammond/pywin32
        #   win32api.OpenProcess(access, inherit, pid) → handle
        #   win32api.TerminateProcess(handle, exit_code) → bool
        #   win32api.CloseHandle(handle)
        if pid is not None:
            try:
                import win32api  # type: ignore[import-not-found]
                import win32con  # type: ignore[import-not-found]

                handle = win32api.OpenProcess(
                    _PROCESS_TERMINATE, False, pid
                )
                try:
                    win32api.TerminateProcess(handle, 1)
                    killed = True
                    log.info(
                        "sw.worker_pool.process_killed",
                        reason=reason,
                        pid=pid,
                        strategy="pywin32_terminate",
                    )
                finally:
                    win32api.CloseHandle(handle)
            except ImportError:
                log.debug(
                    "sw.worker_pool.pywin32_unavailable",
                    reason=reason,
                )
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "sw.worker_pool.pywin32_kill_failed",
                    reason=reason,
                    pid=pid,
                    error=str(e),
                )

        # 策略 3：taskkill /F /PID {pid}（Windows 命令，无需 pywin32）
        if not killed and pid is not None:
            try:
                ret = subprocess.call(
                    ["taskkill", "/F", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10.0,
                )
                if ret == 0:
                    killed = True
                    log.info(
                        "sw.worker_pool.process_killed",
                        reason=reason,
                        pid=pid,
                        strategy="taskkill_pid",
                    )
                else:
                    log.warning(
                        "sw.worker_pool.taskkill_pid_failed",
                        reason=reason,
                        pid=pid,
                        exit_code=ret,
                    )
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "sw.worker_pool.taskkill_pid_exception",
                    reason=reason,
                    pid=pid,
                    error=str(e),
                )

        # 策略 4：taskkill /F /IM sldworks.exe（按映像名 kill，最终降级）
        if not killed:
            try:
                ret = subprocess.call(
                    ["taskkill", "/F", "/IM", "sldworks.exe"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10.0,
                )
                # ret=128 表示无此进程（已退出），视为成功
                if ret in (0, 128):
                    killed = True
                    log.info(
                        "sw.worker_pool.process_killed",
                        reason=reason,
                        strategy="taskkill_image",
                        exit_code=ret,
                    )
                else:
                    log.warning(
                        "sw.worker_pool.taskkill_image_failed",
                        reason=reason,
                        exit_code=ret,
                    )
            except FileNotFoundError:
                # Linux 无 taskkill 命令
                log.info(
                    "sw.worker_pool.taskkill_unavailable",
                    reason=reason,
                    detail="taskkill not found (non-Windows platform)",
                )
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "sw.worker_pool.taskkill_image_exception",
                    reason=reason,
                    error=str(e),
                )

        # 清空会话对象引用（kill 后 COM 对象已失效）
        try:
            self._session._sw_app = None  # type: ignore[attr-defined]
            self._session._started = False  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

        return killed

    # ===== SubTask 7.4：带重试的重启 =====

    def _restart_with_retry(
        self,
        max_retries: int = 3,
        backoff: float = 2.0,
        reason: str = "",
    ) -> None:
        """带指数退避的重启重试（SubTask 7.4）。

        重启失败超过 max_retries → 标记 unhealthy 并抛 SolidWorksSessionError。

        Args:
            max_retries: 最大重试次数（默认 3）
            backoff: 退避基数（秒，指数退避：backoff ** attempt）
            reason: 重启原因（记录到 last_restart_reason，通知回调）

        Raises:
            SolidWorksSessionError: 重启失败超过 max_retries
        """
        with self._restart_lock:
            self._set_health_status(HealthStatus.RESTARTING)
            last_error: Exception | None = None

            for attempt in range(1, max_retries + 1):
                try:
                    log.info(
                        "sw.worker_pool.restart_attempt",
                        attempt=attempt,
                        max_retries=max_retries,
                        reason=reason,
                    )
                    self._session.close()
                    self._session.start()
                    # 更新 session 线程标识（重启可能在不同线程触发）
                    self._session_thread = threading.current_thread()
                    # 重启成功：重置状态
                    self._restart_count += 1
                    self._last_restart_reason = reason
                    self._consecutive_failures = 0
                    self._last_healthy_time = time.monotonic()
                    self._set_health_status(HealthStatus.HEALTHY)
                    log.info(
                        "sw.worker_pool.restart_complete",
                        revision=self._session.revision,
                        attempt=attempt,
                        restart_count=self._restart_count,
                        reason=reason,
                    )
                    # 通知回调
                    self._notify_restart(reason)
                    return
                except Exception as e:  # noqa: BLE001
                    last_error = e
                    log.warning(
                        "sw.worker_pool.restart_attempt_failed",
                        attempt=attempt,
                        max_retries=max_retries,
                        error=str(e),
                    )
                    if attempt < max_retries:
                        sleep_sec = backoff ** attempt
                        log.info(
                            "sw.worker_pool.restart_backoff",
                            sleep=sleep_sec,
                            next_attempt=attempt + 1,
                        )
                        time.sleep(sleep_sec)

            # 全部重试失败
            self._set_health_status(HealthStatus.UNHEALTHY)
            self._last_restart_reason = reason
            msg = (
                f"SolidWorks 会话重启失败（{max_retries} 次重试均失败）"
                f"，原因：{reason}，最后错误：{last_error}"
            )
            log.error(
                "sw.worker_pool.restart_exhausted",
                reason=reason,
                max_retries=max_retries,
                error=str(last_error),
            )
            raise SolidWorksSessionError(msg) from last_error

    def _start_health_check(self) -> None:
        """启动定时健康检查（SubTask 7.4 增强分级恢复）。"""
        if self._health_check_running:
            return
        self._health_check_running = True

        def _check_loop() -> None:
            if not self._health_check_running:
                return
            try:
                healthy = self.health_check()
                if not healthy:
                    # 分级恢复策略（SubTask 7.4）
                    if self._consecutive_failures >= self._max_consecutive_failures:
                        # 连续失败超阈值：硬重启（kill + restart）
                        log.warning(
                            "sw.worker_pool.health_check_hard_restart",
                            consecutive_failures=self._consecutive_failures,
                        )
                        # 不在健康检查线程中 kill（可能阻塞）；
                        # 仅触发 restart，restart 内部会 close + start
                        try:
                            self._restart_with_retry(
                                reason="health_check_consecutive_failures"
                            )
                        except SolidWorksSessionError as e:
                            log.error(
                                "sw.worker_pool.health_check_restart_failed",
                                error=str(e),
                            )
                    else:
                        # 软重启尝试（单次 close + start，无重试）
                        log.info(
                            "sw.worker_pool.health_check_soft_restart",
                            consecutive_failures=self._consecutive_failures,
                        )
                        try:
                            self._restart_with_retry(
                                max_retries=1,
                                reason="health_check_soft_restart",
                            )
                        except SolidWorksSessionError as e:
                            log.warning(
                                "sw.worker_pool.soft_restart_failed",
                                error=str(e),
                            )
            except Exception as e:  # noqa: BLE001
                log.error("sw.worker_pool.health_check_error", error=str(e))
            # 重新调度
            self._health_check_timer = threading.Timer(
                self._health_check_interval, _check_loop
            )
            self._health_check_timer.daemon = True
            self._health_check_timer.start()

        self._health_check_timer = threading.Timer(
            self._health_check_interval, _check_loop
        )
        self._health_check_timer.daemon = True
        self._health_check_timer.start()
        log.info(
            "sw.worker_pool.health_check_started",
            interval=self._health_check_interval,
        )

    def _stop_health_check(self) -> None:
        """停止定时健康检查。"""
        self._health_check_running = False
        if self._health_check_timer:
            self._health_check_timer.cancel()
            self._health_check_timer = None


# ===== 任务装饰器（便捷封装）=====

def solidworks_task(
    timeout: float = 60.0,
    visible: bool = False,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """装饰器：将函数包装为 SolidWorks 任务。

    自动管理 Worker Pool 生命周期：
    - 首次调用时自动启动 Worker Pool（懒启动）
    - 任务执行前健康检查，崩溃则自动重启
    - 任务超时抛 SolidWorksTaskTimeout

    用法：
        @solidworks_task(timeout=120)
        def my_task(session: SolidWorksSession, file_path: Path) -> dict:
            doc = session.open_document(file_path, SW_DOC_PART)
            # ... 业务逻辑
            session.close_document(doc)
            return {...}

        result = my_task(Path("part.slprt"))

    Args:
        timeout: 任务硬超时（秒）
        visible: 是否显示 SolidWorks GUI

    Returns:
        装饰器函数
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            pool = get_worker_pool()
            if not pool.session_started:
                pool.start(visible=visible)
            return pool.submit(fn, *args, timeout=timeout, **kwargs)

        # 暴露原始函数与配置
        wrapper._raw_fn = fn  # type: ignore[attr-defined]
        wrapper._timeout = timeout  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ===== 全局单例获取 =====

_pool_instance: SolidWorksWorkerPool | None = None
_pool_lock = threading.Lock()


def get_worker_pool(max_workers: int = 1) -> SolidWorksWorkerPool:
    """获取全局 SolidWorksWorkerPool 单例。

    Args:
        max_workers: 最大 Worker 数（仅首次调用生效）

    Returns:
        SolidWorksWorkerPool 实例（可能未启动）
    """
    global _pool_instance
    if _pool_instance is None:
        with _pool_lock:
            if _pool_instance is None:
                _pool_instance = SolidWorksWorkerPool(max_workers=max_workers)
    return _pool_instance


# ===== SubTask 17.1: 模块级预热便捷函数 =====


def prewarm_pool(count: int | None = None) -> dict[str, Any]:
    """模块级预热便捷函数（SubTask 17.1）。

    Args:
        count: 预热数量；None 时读 settings.SOLIDWORKS_PREWARM_COUNT

    Returns:
        prewarm 结果 dict（见 SolidWorksWorkerPool.prewarm_pool）
    """
    if count is None:
        try:
            from app.config import settings

            count = int(getattr(settings, "SOLIDWORKS_PREWARM_COUNT", 0))
        except Exception:  # noqa: BLE001
            count = 0
    pool = get_worker_pool()
    return pool.prewarm_pool(count=count)


# ===== SubTask 7.4：离线自检 =====

def _self_test() -> dict[str, Any]:
    """离线自检：验证模块导入与 SubTask 7.4 + 7.6 增强完整性。

    本函数不调用 SolidWorks API，可在 Linux 环境运行。
    用于 CI / 离线环境验证模块完整性。

    Returns:
        {"ok": bool, "errors": list[str], "checks": dict[str, bool]}
    """
    checks: dict[str, bool] = {}
    errors: list[str] = []

    # 1. 模块导入安全
    try:
        from app.services.solidworks.sw_session import (  # noqa: F401
            is_solidworks_available,
        )
        checks["session_import"] = True
        checks["available_flag"] = isinstance(is_solidworks_available(), bool)
    except Exception as e:  # noqa: BLE001
        checks["session_import"] = False
        errors.append(f"session 导入失败: {e}")

    # 2. HealthStatus 枚举完整
    try:
        from app.services.solidworks.status import HealthStatus

        expected = {"healthy", "degraded", "unhealthy", "restarting", "stopped"}
        actual = {s.value for s in HealthStatus}
        checks["health_status_enum"] = actual == expected
        # 验证继承 str 便于序列化
        checks["health_status_str"] = isinstance(
            HealthStatus.HEALTHY, str
        ) and HealthStatus.HEALTHY == "healthy"
    except Exception as e:  # noqa: BLE001
        checks["health_status_enum"] = False
        errors.append(f"HealthStatus 枚举校验失败: {e}")

    # 3. SolidWorksWorkerPool 类 API 完整（不实例化，避免依赖 pywin32）
    try:
        # 新增公共方法 callable（unbound 检查）
        new_methods = [
            "acquire_slot",
            "release_slot",
            "wait_for_idle",
            "register_on_restart",
        ]
        for m in new_methods:
            checks[f"method_{m}_callable"] = callable(
                getattr(SolidWorksWorkerPool, m, None)
            )

        # 新增私有方法 callable
        private_methods = [
            "_kill_solidworks_process",
            "_restart_with_retry",
        ]
        for m in private_methods:
            checks[f"method_{m}_callable"] = callable(
                getattr(SolidWorksWorkerPool, m, None)
            )

        # 新增属性（作为 property 存在于类上）
        new_props = [
            "is_busy",
            "health_status",
            "max_concurrent_sessions",
            "consecutive_failures",
            "restart_count",
            "last_restart_reason",
            "last_health_check_time",
            "last_healthy_time",
            # SubTask 7.6 新增属性
            "license_status",
            "max_licenses",
            "license_manager",
        ]
        for p in new_props:
            obj = getattr(SolidWorksWorkerPool, p, None)
            checks[f"prop_{p}_exists"] = obj is not None
    except Exception as e:  # noqa: BLE001
        checks["class_api"] = False
        errors.append(f"类 API 校验失败: {e}")

    # 4. 默认配置值（通过 __init__ 签名检查）
    try:
        import inspect

        sig = inspect.signature(SolidWorksWorkerPool.__init__)
        params = sig.parameters
        # max_concurrent_sessions 参数存在且默认 1
        mcs = params.get("max_concurrent_sessions")
        checks["init_has_max_concurrent_sessions"] = mcs is not None
        if mcs is not None and mcs.default is not inspect.Parameter.empty:
            checks["default_max_concurrent_sessions_1"] = mcs.default == 1
        else:
            checks["default_max_concurrent_sessions_1"] = False
    except Exception as e:  # noqa: BLE001
        checks["init_signature"] = False
        errors.append(f"__init__ 签名检查失败: {e}")

    # 5. 既有公共 API 未被破坏
    try:
        checks["solidworks_task_callable"] = callable(solidworks_task)
        checks["get_worker_pool_callable"] = callable(get_worker_pool)
        # __all__ 导出完整
        expected_all = {"SolidWorksWorkerPool", "get_worker_pool", "solidworks_task"}
        checks["all_exports_complete"] = expected_all.issubset(set(__all__))
    except Exception as e:  # noqa: BLE001
        checks["public_api"] = False
        errors.append(f"公共 API 校验失败: {e}")

    # 6. 异常类仍可导入
    try:
        from app.services.solidworks.exceptions import (  # noqa: F401
            SolidWorksLicenseError,
            SolidWorksSessionError,
            SolidWorksTaskError,
            SolidWorksTaskTimeout,
        )
        checks["exceptions_import"] = True
    except Exception as e:  # noqa: BLE001
        checks["exceptions_import"] = False
        errors.append(f"异常类导入失败: {e}")

    # 7. SubTask 7.6：许可证管理器集成校验
    try:
        from app.services.solidworks.license import (
            LicenseStatus,
            SolidWorksLicenseManager,
        )

        # LicenseStatus 枚举完整
        expected_lic = {"available", "in_use", "exhausted", "unknown"}
        actual_lic = {s.value for s in LicenseStatus}
        checks["license_status_enum_complete"] = actual_lic == expected_lic

        # SolidWorksLicenseManager 可导入
        checks["license_manager_importable"] = (
            SolidWorksLicenseManager is not None
        )

        # worker_pool 模块导入了 license 模块（验证集成）
        # 通过检查模块级导入是否成功（间接验证循环依赖无问题）
        import app.services.solidworks.worker_pool as wp_mod

        checks["worker_pool_imports_license"] = hasattr(
            wp_mod, "SolidWorksLicenseManager"
        ) and hasattr(wp_mod, "LicenseStatus")
    except Exception as e:  # noqa: BLE001
        checks["license_integration"] = False
        errors.append(f"许可证管理器集成校验失败: {e}")

    # 8. SubTask 17.1：prewarm_pool 方法与模块级函数校验
    try:
        # 类方法存在且可调用
        checks["prewarm_pool_method_callable"] = callable(
            getattr(SolidWorksWorkerPool, "prewarm_pool", None)
        )
        # 模块级函数存在且可调用
        checks["prewarm_pool_module_callable"] = callable(
            getattr(wp_mod, "prewarm_pool", None)
        )
        # __all__ 包含 prewarm_pool
        checks["prewarm_pool_exported"] = "prewarm_pool" in (
            getattr(wp_mod, "__all__", []) or []
        )
        # prewarm_pool(0) 无副作用：返回 status=skipped
        result_zero = prewarm_pool(count=0)
        checks["prewarm_zero_skipped"] = (
            isinstance(result_zero, dict)
            and result_zero.get("status") == "skipped"
            and result_zero.get("count") == 0
        )
        # prewarm_pool(1) 优雅降级（无 SolidWorks 时返回 degraded，不抛异常）
        result_one = prewarm_pool(count=1)
        checks["prewarm_one_no_raise"] = isinstance(result_one, dict)
        checks["prewarm_one_status_valid"] = result_one.get("status") in {
            "ok", "already_started", "degraded",
        }
    except Exception as e:  # noqa: BLE001
        checks["prewarm_pool_check"] = False
        errors.append(f"prewarm_pool 校验失败: {e}")

    ok = all(checks.values())
    return {"ok": ok, "errors": errors, "checks": checks}


__all__ = [
    "SolidWorksWorkerPool",
    "get_worker_pool",
    "solidworks_task",
    "prewarm_pool",
]
