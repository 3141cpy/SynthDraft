"""审图依赖探测与缺失错误。

各文件类型所需依赖的可用性检测，缺失时抛出 DependencyMissingError 含安装指引。
"""

from __future__ import annotations


class DependencyMissingError(Exception):
    """所需依赖不可用，无法处理该文件类型。"""

    def __init__(self, dependency_name: str, install_hint: str, file_type: str = ""):
        self.dependency_name = dependency_name
        self.install_hint = install_hint
        self.file_type = file_type
        super().__init__(f"处理 {file_type} 文件需要 {dependency_name}：{install_hint}")


def is_pypdfium2_available() -> bool:
    """检测 pypdfium2 是否可用。"""
    try:
        import pypdfium2  # noqa: F401
        return True
    except ImportError:
        return False


def is_trimesh_pyrender_available() -> bool:
    """检测 trimesh + pyrender 是否可用（STEP/IGES 渲染降级方案）。

    优先使用 scikit-robot-pyrender（fork 版本，自动 OpenGL 降级 + 软件渲染），
    缺失时回退原版 pyrender（headless 环境可能失败）。
    """
    try:
        import trimesh  # noqa: F401
        import pyrender  # noqa: F401
        return True
    except ImportError:
        return False


def is_sw_docmgr_available() -> bool:
    """检测 SolidWorks Document Manager API 是否可用。

    需要：pythonnet + SwDocumentMgr.dll + license key。
    仅 Windows。
    """
    import sys
    if sys.platform != "win32":
        return False
    try:
        from app.config import settings
        if not settings.SW_DOCMGR_LICENSE_KEY:
            return False
        if not settings.SW_DOCMGR_DLL_PATH:
            return False
        import os
        if not os.path.isfile(settings.SW_DOCMGR_DLL_PATH):
            return False
        # pythonnet 可导入即认为可用（实际加载 DLL 在调用时做）
        import clr  # noqa: F401
        return True
    except ImportError:
        return False
    except Exception:
        return False


def is_shell_thumbnail_available() -> bool:
    """检测 Windows Shell Thumbnail 提取是否可用。

    双路径支持：
    - 路径 A（主）：ctypes 直接调用 IShellItemImageFactory，仅需 pywin32/pythoncom + PIL
    - 路径 B（备）：pythonnet + WindowsAPICodePack.Shell.dll

    路径 A 在 Windows + CPython 上始终可用（ctypes 内置）。
    SolidWorks Shell Extension 是否注册在渲染时实际探测，此处仅检查基础依赖。
    """
    import sys
    if sys.platform != "win32":
        return False
    # 路径 A：ctypes（内置）+ PIL
    try:
        import ctypes  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        pass
    # 路径 B：pythonnet + WindowsAPICodePack
    try:
        import clr  # noqa: F401
        clr.AddReference("Microsoft.WindowsAPICodePack.Shell")
        return True
    except Exception:
        return False


def is_solidworks_available() -> bool:
    """检测 SolidWorks COM（pywin32 + SolidWorks 主程序）是否可用。

    复用 sw_session.is_solidworks_available，此处封装为统一入口，
    便于 SLDPRT/SLDASM 降级链路从 dependency_check 统一导入所有探测函数。
    """
    try:
        from app.services.solidworks.sw_session import is_solidworks_available as _impl

        return _impl()
    except Exception:
        return False


def is_edrawings_available() -> bool:
    """检测 eDrawings CLI 是否可用（SLDPRT/SLDASM L3a 降级）。

    需要：eDrawings 安装 + 外部 C# CLI 工具 edrawings_export.exe。
    仅 Windows。
    """
    import sys
    if sys.platform != "win32":
        return False
    try:
        from app.services.solidworks.edrawings_cli import is_edrawings_available as _impl
        return _impl()
    except Exception:
        return False
