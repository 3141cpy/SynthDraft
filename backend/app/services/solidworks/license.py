"""SolidWorks 许可证管理（SubTask 7.6）。

职责：
- 许可证状态检测（通过 Dispatch SldWorks.Application 验证可用性）
- 许可证计数（控制并发实例数，避免超限）
- 线程安全（基于 threading.Lock）
- 跨平台降级（Linux/无 pywin32 时 get_status 返回 UNKNOWN，acquire 返回 False）

设计原则（遵循"以瞎猜接口为耻"）：
- SolidWorks 无公开的许可证查询 API，本模块采用"尝试 Dispatch + 立即关闭"策略
  验证许可证可用性（轻量级探测，启动后立即 ExitApp）
- 计数控制为内存计数（不依赖许可证服务器的远程状态），用于限制进程内并发
- 实际的许可证占用由 SolidWorksSession.start() 触发（Dispatch 时由 SolidWorks
  自动向许可证服务器申请），本模块的 acquire/release 仅做计数前置校验

API 参考：
- SolidWorks API Help 2025: https://help.solidworks.com/2025/english/api/sldworksapiprogguide/
- SldWorks.Application Dispatch ProgID（与 sw_session.py 一致）
- ISldWorks::RevisionNumber：读取版本号验证实例存活
- ISldWorks::ExitApp：退出实例释放许可证

部署约束（spec.md §3）：
SolidWorks 原生文件操作必须在装有 SolidWorks 许可证的 Windows 机器上。
Linux 部署 AI 服务时，本模块降级为 UNKNOWN 状态，不阻塞 AI 服务运行。
"""

from __future__ import annotations

import threading
from typing import Any

from app.logging import get_logger
from app.services.solidworks.sw_session import is_solidworks_available

log = get_logger(__name__)


# ===== 许可证状态枚举 =====


from enum import Enum


class LicenseStatus(str, Enum):
    """SolidWorks 许可证状态。

    继承 str 便于 JSON 序列化与日志结构化字段输出。
    """

    AVAILABLE = "available"
    """可用：许可证可被获取（探测成功且未超限）。"""

    IN_USE = "in_use"
    """使用中：已获取但未超限（探测成功且 current_usage > 0）。"""

    EXHAUSTED = "exhausted"
    """耗尽：并发数已达上限或许可证服务器拒绝（探测时遇到 license 错误）。"""

    UNKNOWN = "unknown"
    """未知：pywin32 未安装 / 非 Windows 平台 / 探测异常。"""


# ===== 许可证管理器 =====


class SolidWorksLicenseManager:
    """SolidWorks 许可证管理器（线程安全，进程内单例）。

    用法：
        mgr = SolidWorksLicenseManager(max_licenses=1)
        status = mgr.get_status()  # 探测实际状态（耗时 ~10s）
        if mgr.acquire():          # 计数 +1
            try:
                # 启动 SolidWorks 实例（实际占用许可证）
                ...
            finally:
                mgr.release()      # 计数 -1

    设计说明：
    - ``acquire``/``release`` 仅做内存计数，不与许可证服务器通信
    - ``get_status`` 通过 Dispatch 探测实际可用性（耗时，不作为 acquire 的前置条件）
    - ``is_available`` 基于计数快速判断，不触发 Dispatch
    - 跨平台降级：Linux/无 pywin32 时 acquire 返回 False，get_status 返回 UNKNOWN
    """

    def __init__(self, max_licenses: int = 1) -> None:
        self._max_licenses = max(1, max_licenses)
        self._current_usage = 0
        self._lock = threading.Lock()
        self._last_status: LicenseStatus = LicenseStatus.UNKNOWN
        self._last_probe_time: float | None = None

    # ===== 属性 =====

    @property
    def max_licenses(self) -> int:
        """最大许可证数（并发上限）。"""
        return self._max_licenses

    @property
    def current_usage(self) -> int:
        """当前已获取的许可证数。"""
        with self._lock:
            return self._current_usage

    @property
    def is_available(self) -> bool:
        """许可证是否可用（基于计数快速判断，不触发 Dispatch）。

        跨平台降级：Linux/无 pywin32 时返回 False。
        """
        if not is_solidworks_available():
            return False
        with self._lock:
            return self._current_usage < self._max_licenses

    @property
    def last_status(self) -> LicenseStatus:
        """上次探测到的许可证状态（由 get_status 更新）。"""
        return self._last_status

    @property
    def last_probe_time(self) -> float | None:
        """上次探测时间戳（monotonic，None 表示从未探测）。"""
        return self._last_probe_time

    # ===== 状态探测 =====

    def get_status(self) -> LicenseStatus:
        """探测 SolidWorks 许可证实际状态（耗时 ~10s，慎用）。

        策略：尝试 Dispatch SldWorks.Application，读取 RevisionNumber 验证实例可用，
        然后立即 ExitApp 释放。探测成功表示许可证可用。

        跨平台降级：
        - Linux/无 pywin32：返回 UNKNOWN，不抛异常
        - Dispatch 失败且错误信息含 "license"：返回 EXHAUSTED
        - 其他异常：返回 UNKNOWN

        Returns:
            LicenseStatus 枚举值
        """
        if not is_solidworks_available():
            self._last_status = LicenseStatus.UNKNOWN
            return LicenseStatus.UNKNOWN

        import time

        # 复用 sw_session 的 pywin32 句柄（保证 import 路径一致）
        try:
            import pythoncom  # type: ignore[import-not-found]
            import win32com.client  # type: ignore[import-not-found]
        except ImportError:
            self._last_status = LicenseStatus.UNKNOWN
            return LicenseStatus.UNKNOWN

        probe_start = time.monotonic()
        sw_app: Any = None
        co_initialized = False
        try:
            pythoncom.CoInitialize()
            co_initialized = True
            sw_app = win32com.client.Dispatch("SldWorks.Application")
            # 设置不可见 + 不允许用户控制，避免抢占前台
            try:
                sw_app.Visible = False
                sw_app.UserControl = False
            except Exception:  # noqa: BLE001
                pass
            # 读取版本号验证实例可用（许可证有效才能成功）
            _ = sw_app.RevisionNumber

            # 探测成功：基于计数判断 AVAILABLE / IN_USE
            with self._lock:
                if self._current_usage >= self._max_licenses:
                    self._last_status = LicenseStatus.EXHAUSTED
                elif self._current_usage > 0:
                    self._last_status = LicenseStatus.IN_USE
                else:
                    self._last_status = LicenseStatus.AVAILABLE
            log.info(
                "sw.license.probe_ok",
                status=self._last_status.value,
                usage=self._current_usage,
                max=self._max_licenses,
            )
            return self._last_status
        except Exception as e:  # noqa: BLE001
            err_msg = str(e).lower()
            if "license" in err_msg or "许可" in err_msg:
                self._last_status = LicenseStatus.EXHAUSTED
                log.warning(
                    "sw.license.probe_exhausted",
                    error=str(e),
                )
            else:
                self._last_status = LicenseStatus.UNKNOWN
                log.warning(
                    "sw.license.probe_unknown",
                    error=str(e),
                )
            return self._last_status
        finally:
            # 仅当无活跃会话时才 ExitApp，避免终止由 SolidWorksSession 管理的实例
            # （SolidWorks COM 通常是单实例，Dispatch 会返回已运行的实例）
            if sw_app is not None:
                with self._lock:
                    should_exit = self._current_usage == 0
                if should_exit:
                    try:
                        sw_app.ExitApp()
                    except Exception:  # noqa: BLE001
                        pass
            if co_initialized:
                try:
                    pythoncom.CoUninitialize()
                except Exception:  # noqa: BLE001
                    pass
            self._last_probe_time = probe_start

    # ===== 计数控制 =====

    def acquire(self) -> bool:
        """获取许可证槽位（计数 +1）。

        跨平台降级：Linux/无 pywin32 时返回 False。

        Returns:
            True 表示获取成功；False 表示并发已满或平台不支持
        """
        if not is_solidworks_available():
            log.debug(
                "sw.license.acquire_unavailable",
                reason="pywin32 not installed or non-Windows platform",
            )
            return False
        with self._lock:
            if self._current_usage >= self._max_licenses:
                log.warning(
                    "sw.license.acquire_exhausted",
                    usage=self._current_usage,
                    max=self._max_licenses,
                )
                return False
            self._current_usage += 1
            log.info(
                "sw.license.acquired",
                usage=self._current_usage,
                max=self._max_licenses,
            )
            return True

    def release(self) -> None:
        """释放许可证槽位（计数 -1）。

        幂等：计数已为 0 时再调用安全（仅记日志）。
        """
        with self._lock:
            if self._current_usage <= 0:
                log.warning(
                    "sw.license.release_underflow",
                    usage=self._current_usage,
                )
                return
            self._current_usage -= 1
            log.info(
                "sw.license.released",
                usage=self._current_usage,
                max=self._max_licenses,
            )

    def reset(self) -> None:
        """重置计数（仅用于测试或故障恢复）。

        注意：生产环境慎用，可能导致计数与实际许可证占用不一致。
        """
        with self._lock:
            old = self._current_usage
            self._current_usage = 0
            log.warning(
                "sw.license.reset",
                old_usage=old,
            )


# ===== 全局单例获取 =====

_license_manager_instance: SolidWorksLicenseManager | None = None
_license_manager_lock = threading.Lock()


def get_license_manager(max_licenses: int = 1) -> SolidWorksLicenseManager:
    """获取全局 SolidWorksLicenseManager 单例。

    Args:
        max_licenses: 最大许可证数（仅首次调用生效）

    Returns:
        SolidWorksLicenseManager 实例
    """
    global _license_manager_instance
    if _license_manager_instance is None:
        with _license_manager_lock:
            if _license_manager_instance is None:
                _license_manager_instance = SolidWorksLicenseManager(
                    max_licenses=max_licenses
                )
    return _license_manager_instance


# ===== 离线自检 =====


def _self_test() -> dict[str, Any]:
    """离线自检：验证模块导入与许可证管理逻辑完整。

    本函数不调用 SolidWorks API（不触发 Dispatch），可在 Linux 环境运行。
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

    # 2. LicenseStatus 枚举完整
    try:
        expected = {"available", "in_use", "exhausted", "unknown"}
        actual = {s.value for s in LicenseStatus}
        checks["license_status_enum"] = actual == expected
        # 验证继承 str 便于序列化
        checks["license_status_str"] = (
            isinstance(LicenseStatus.AVAILABLE, str)
            and LicenseStatus.AVAILABLE == "available"
        )
    except Exception as e:  # noqa: BLE001
        checks["license_status_enum"] = False
        errors.append(f"LicenseStatus 枚举校验失败: {e}")

    # 3. SolidWorksLicenseManager 可实例化（不依赖 SolidWorks 实例）
    try:
        mgr = SolidWorksLicenseManager(max_licenses=2)
        checks["manager_instantiable"] = True
        checks["max_licenses_prop"] = mgr.max_licenses == 2
        checks["current_usage_prop"] = mgr.current_usage == 0
        checks["last_status_initial"] = mgr.last_status == LicenseStatus.UNKNOWN
        checks["last_probe_time_initial"] = mgr.last_probe_time is None
    except Exception as e:  # noqa: BLE001
        checks["manager_instantiable"] = False
        errors.append(f"SolidWorksLicenseManager 实例化失败: {e}")

    # 4. acquire/release 计数逻辑（不依赖 SolidWorks 实例）
    #    通过临时 patch is_solidworks_available 模拟跨平台场景，
    #    避免在 self_test 中触发真实 Dispatch（耗时 ~10s）
    try:
        import app.services.solidworks.license as license_mod

        original_avail = license_mod.is_solidworks_available

        # 4a. 模拟 Windows + pywin32 可用：acquire/release 计数逻辑
        license_mod.is_solidworks_available = lambda: True  # type: ignore
        try:
            mgr = SolidWorksLicenseManager(max_licenses=1)
            checks["acquire_first_ok"] = mgr.acquire() is True
            checks["usage_after_acquire"] = mgr.current_usage == 1
            # 第二次 acquire 应失败（超限）
            checks["acquire_second_exhausted"] = mgr.acquire() is False
            checks["usage_still_one"] = mgr.current_usage == 1
            # is_available 应为 False（已耗尽）
            checks["is_available_false_when_exhausted"] = (
                mgr.is_available is False
            )
            # release 后计数归零
            mgr.release()
            checks["usage_after_release"] = mgr.current_usage == 0
            # release 再次调用应安全（幂等，不降到负数）
            mgr.release()
            checks["usage_idempotent_release"] = mgr.current_usage == 0
            # reset 重置
            mgr.acquire()
            mgr.reset()
            checks["usage_after_reset"] = mgr.current_usage == 0
            # is_available 在未耗尽时为 True
            checks["is_available_true_when_free"] = mgr.is_available is True
        finally:
            license_mod.is_solidworks_available = original_avail  # type: ignore

        # 4b. 模拟 Linux/无 pywin32：acquire 返回 False，is_available 返回 False
        license_mod.is_solidworks_available = lambda: False  # type: ignore
        try:
            mgr = SolidWorksLicenseManager(max_licenses=1)
            checks["acquire_unavailable_degraded"] = mgr.acquire() is False
            checks["is_available_false_degraded"] = mgr.is_available is False
            # get_status 在降级时应返回 UNKNOWN（不触发 Dispatch，不抛异常）
            status = mgr.get_status()
            checks["get_status_unknown_degraded"] = (
                status == LicenseStatus.UNKNOWN
            )
            checks["get_status_no_raise_degraded"] = isinstance(
                status, LicenseStatus
            )
        finally:
            license_mod.is_solidworks_available = original_avail  # type: ignore

        # 单例获取
        single = get_license_manager(max_licenses=1)
        checks["singleton_callable"] = isinstance(
            single, SolidWorksLicenseManager
        )
    except Exception as e:  # noqa: BLE001
        checks["acquire_release_logic"] = False
        errors.append(f"acquire/release 计数逻辑校验失败: {e}")

    # 6. 公共 API 完整
    try:
        checks["license_status_exported"] = LicenseStatus is not None
        checks["manager_class_exported"] = SolidWorksLicenseManager is not None
        checks["get_license_manager_callable"] = callable(get_license_manager)
    except Exception as e:  # noqa: BLE001
        checks["public_api"] = False
        errors.append(f"公共 API 校验失败: {e}")

    ok = all(checks.values())
    return {"ok": ok, "errors": errors, "checks": checks}


__all__ = [
    "LicenseStatus",
    "SolidWorksLicenseManager",
    "get_license_manager",
]


if __name__ == "__main__":  # pragma: no cover
    import json

    result = _self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    import sys

    sys.exit(0 if result["ok"] else 1)
