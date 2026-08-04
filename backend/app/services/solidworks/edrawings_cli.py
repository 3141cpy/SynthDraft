"""eDrawings CLI 渲染器（SLDPRT/SLDASM 预览图提取 L3a 降级）。

eDrawings 是免费的 SolidWorks 文件查看器（~200MB），无需 SolidWorks License。
下载：https://www.edrawingsviewer.com/

降级链路位置（L3a，在 L2 Shell Thumbnail 和 L3b SolidWorks COM 之间）：
1. L1：SolidWorks Document Manager API（需 license key）
2. L2：Windows Shell Thumbnail（需 WindowsAPICodePack）
3. L3a：eDrawings CLI（本模块，免费，无需 SW License）
4. L3b：SolidWorks COM（需 SolidWorks 主程序 + License）

实现说明：
eDrawings 本身是 GUI 应用，不提供官方命令行导出 PNG 的接口。
本模块提供两种导出路径：
- 路径 A（推荐）：调用外部 C# CLI 工具 edrawings_export.exe（若存在）
  该工具使用 EModelViewControl OCX 加载 SLDPRT/SLDASM 后导出 PNG
  C# 项目源码位于 backend/app/services/solidworks/edrawings_export/
- 路径 B（兜底）：直接调用 eDrawings.exe 打开文件（仅启动查看，不导出 PNG）
  此路径返回 None，由 pipeline 降级到 L3b

依赖：
- eDrawings 安装（EDRAWINGS_PATH 配置或注册表查找）
- 外部 C# CLI 工具 edrawings_export.exe（可选，路径 A）
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.logging import get_logger

log = get_logger(__name__)

# C# CLI 工具默认路径（若编译存在）
_EDRAWINGS_EXPORT_CLI_NAME = "edrawings_export.exe"
_EDRAWINGS_EXPORT_CLI_DEFAULT_PATH = (
    Path(__file__).parent / "edrawings_export" / "bin" / _EDRAWINGS_EXPORT_CLI_NAME
)

# eDrawings 默认安装路径（Windows）
_EDRAWINGS_DEFAULT_PATHS = [
    r"C:\Program Files\Common Files\eDrawings\eDrawings.exe",
    r"C:\Program Files\eDrawings\eDrawings.exe",
    r"C:\Program Files (x86)\eDrawings\eDrawings.exe",
]


def _resolve_edrawings_exe() -> str | None:
    """解析 eDrawings 可执行文件路径。

    优先级：
    1. 配置 EDRAWINGS_PATH（app.config.settings.EDRAWINGS_PATH）
    2. 常见安装路径探测
    3. PATH 查找

    Returns:
        eDrawings.exe 路径；未找到返回 None
    """
    # 1. 配置项
    try:
        from app.config import settings
        configured = (settings.EDRAWINGS_PATH or "").strip().strip('"')
        if configured and Path(configured).is_file():
            return configured
    except Exception:  # noqa: BLE001
        pass

    # 2. 常见安装路径
    for path in _EDRAWINGS_DEFAULT_PATHS:
        if Path(path).is_file():
            return path

    # 3. PATH 查找
    import shutil
    return shutil.which("eDrawings") or shutil.which("eDrawings.exe")


def _resolve_export_cli() -> str | None:
    """解析外部 C# CLI 工具 edrawings_export.exe 路径。

    Returns:
        edrawings_export.exe 路径；未找到返回 None（路径 A 不可用）
    """
    # 环境变量覆盖
    env_path = os.environ.get("EDRAWINGS_EXPORT_CLI", "").strip().strip('"')
    if env_path and Path(env_path).is_file():
        return env_path

    # 默认编译输出路径
    if _EDRAWINGS_EXPORT_CLI_DEFAULT_PATH.is_file():
        return str(_EDRAWINGS_EXPORT_CLI_DEFAULT_PATH)

    return None


def is_edrawings_available() -> bool:
    """检测 eDrawings 是否可用（路径 A：CLI 工具 + eDrawings 安装）。

    仅当 C# CLI 工具 edrawings_export.exe 存在且 eDrawings 已安装时返回 True。
    仅 eDrawings 安装但无 CLI 工具时返回 False（路径 B 无法导出 PNG）。
    """
    if sys.platform != "win32":
        return False
    edrawings_exe = _resolve_edrawings_exe()
    cli_exe = _resolve_export_cli()
    if edrawings_exe and cli_exe:
        log.debug(
            "solidworks.edrawings.available",
            edrawings=edrawings_exe,
            cli=cli_exe,
        )
        return True
    if edrawings_exe and not cli_exe:
        log.debug(
            "solidworks.edrawings.cli_missing",
            edrawings=edrawings_exe,
            hint="C# CLI 工具未编译，路径 A 不可用；参考 edrawings_export/ 目录编译",
        )
    return False


def render_sldprt_via_edrawings(
    file_path: str | Path, output_path: str | Path
) -> str | None:
    """用 eDrawings CLI 提取 SLDPRT/SLDASM 预览图。

    调用外部 C# CLI 工具 edrawings_export.exe：
        edrawings_export.exe <input.sldprt|sldasm> <output.png> [--edrawings <path>]

    Args:
        file_path: SLDPRT/SLDASM 文件路径
        output_path: 输出 PNG 路径

    Returns:
        输出 PNG 路径；不可用或失败时返回 None
    """
    if sys.platform != "win32":
        log.warning("solidworks.edrawings.not_windows")
        return None

    cli_exe = _resolve_export_cli()
    if not cli_exe:
        log.warning("solidworks.edrawings.cli_not_found")
        return None

    edrawings_exe = _resolve_edrawings_exe()
    if not edrawings_exe:
        log.warning("solidworks.edrawings.exe_not_found")
        return None

    file_path_str = str(file_path)
    output_path_str = str(output_path)
    Path(output_path_str).parent.mkdir(parents=True, exist_ok=True)

    try:
        cmd = [cli_exe, file_path_str, output_path_str, "--edrawings", edrawings_exe]
        log.info(
            "solidworks.edrawings.export_start",
            file=file_path_str,
            output=output_path_str,
            cli=cli_exe,
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=90,  # eDrawings 加载 + 导出超时（CLI 内部硬超时 55s + 余量）
            check=False,
        )
        if result.returncode != 0:
            # CLI 退出码非零时仍检查输出文件是否存在：
            # eDrawings CLI 在 Environment.Exit(0) 前可能因 COM 清理阻塞导致硬超时退出，
            # 但 PNG 文件可能已经成功生成。
            if Path(output_path_str).is_file() and Path(output_path_str).stat().st_size > 0:
                log.info(
                    "solidworks.edrawings.export_done_nonzero_exit",
                    file=file_path_str,
                    png=output_path_str,
                    file_size=Path(output_path_str).stat().st_size,
                    returncode=result.returncode,
                )
                return output_path_str
            log.warning(
                "solidworks.edrawings.export_failed",
                file=file_path_str,
                returncode=result.returncode,
                stderr=result.stderr or "",
            )
            return None
        if not Path(output_path_str).is_file():
            log.warning(
                "solidworks.edrawings.no_output",
                file=file_path_str,
                expected_output=output_path_str,
            )
            return None
        log.info(
            "solidworks.edrawings.export_done",
            file=file_path_str,
            png=output_path_str,
            file_size=Path(output_path_str).stat().st_size,
        )
        return output_path_str
    except subprocess.TimeoutExpired:
        log.warning("solidworks.edrawings.timeout", file=file_path_str, timeout=90)
        return None
    except Exception as e:
        log.warning("solidworks.edrawings.failed", file=file_path_str, error=str(e))
        return None
