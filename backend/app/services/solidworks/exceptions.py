"""SolidWorks Worker 异常定义（Task 7）。

异常层次：
- SolidWorksNotAvailableError：pywin32 未安装或非 Windows 平台
- SolidWorksSessionError：会话创建/操作失败（COM 调用异常）
- SolidWorksTaskTimeout：任务执行超时
- SolidWorksTaskError：任务执行失败（业务异常）
- SolidWorksLicenseError：许可证不可用或并发超限
"""

from __future__ import annotations


class SolidWorksNotAvailableError(RuntimeError):
    """SolidWorks 或 pywin32 不可用。

    可能原因：
    - 非 Windows 平台（Linux 部署 AI 服务时）
    - pywin32 未安装
    - SolidWorks 未安装
    """


class SolidWorksSessionError(RuntimeError):
    """SolidWorks COM 会话异常。

    包括 Dispatch 失败、API 调用异常、进程崩溃等。
    """


class SolidWorksTaskTimeout(TimeoutError):
    """SolidWorks 任务执行超时。"""


class SolidWorksTaskError(RuntimeError):
    """SolidWorks 任务执行失败（业务异常）。

    包括文件打开失败、特征创建失败、保存失败等。
    """


class SolidWorksLicenseError(RuntimeError):
    """SolidWorks 许可证不可用或并发超限。"""


__all__ = [
    "SolidWorksLicenseError",
    "SolidWorksNotAvailableError",
    "SolidWorksSessionError",
    "SolidWorksTaskError",
    "SolidWorksTaskTimeout",
]
