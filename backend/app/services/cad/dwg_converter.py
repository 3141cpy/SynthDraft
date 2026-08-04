"""DWG → DXF 转换封装（SubTask 2.2）。

依赖：
- ezdxf.addons.odafc（ezdxf 自带 addon）
- ODA File Converter（外部独立安装，需注册下载）

官方文档：
- https://ezdxf.readthedocs.io/en/stable/addons/odafc.html
- ODA File Converter 下载：https://www.opendesign.com/guestfiles/oda_file_converter

环境变量：
- 不强制要求；odafc 默认在 PATH 中查找 ODAFileConverter（Linux/macOS）
  或读 ezdxf.options["odafc-addon"]["win_exec_path"]（Windows）。
  也可显式设置环境变量 ODAFC_PATH 指向可执行文件，本模块会将其注入 ezdxf 选项。

版本要求（2026-08-02 调研后更新）：
- 推荐 ODA File Converter 27.1（2026 版，~27MB，AppImage 自带 Qt6 运行时）
- 最低版本 25.x（低于此版本在 Linux 上需手动安装 Qt5/Qt6 运行时，且不兼容 DWG 2026）
- 27.1 起 AppImage 自带 Qt6，跨 Linux 发行版兼容性显著改善

不可用时调用方应捕获 ODANotAvailableError 或先调用 is_odafc_available()。
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import ezdxf
from ezdxf.addons import odafc

__all__ = [
    "ODANotAvailableError",
    "ODAVersionWarning",
    "detect_odafc_version",
    "dwg_to_dxf",
    "is_odafc_available",
]


_ODA_INSTALL_URL = "https://www.opendesign.com/guestfiles/oda_file_converter"
_ODA_DOC_URL = "https://ezdxf.readthedocs.io/en/stable/addons/odafc.html"

# 推荐 / 最低版本（调研后确定，2026-08-02）
_ODA_RECOMMENDED_VERSION = "27.1"
_ODA_MIN_VERSION = "25.0"

# 版本号缓存，避免重复 subprocess 调用
_odafc_version_cache: str | None = None
_odafc_version_checked = False


class ODANotAvailableError(RuntimeError):
    """ODA File Converter 未安装或不在 PATH / ODAFC_PATH 中。"""


class ODAVersionWarning(UserWarning):
    """ODA File Converter 版本过低警告（不阻断，仅提示升级）。"""


def _parse_version_tuple(v: str) -> tuple[int, int]:
    """将 '27.1' / '26.12.8471' 等版本字符串解析为 (major, minor) 元组。

    解析失败时返回 (0, 0)。
    """
    match = re.match(r"(\d+)\.(\d+)", v.strip())
    if not match:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2)))


def _ensure_odafc_path() -> None:
    """若环境变量 ODAFC_PATH 设置，则注入到 ezdxf 选项中（仅 Windows）。

    odafc.is_installed() 在 Windows 上仅检查 ezdxf.options["odafc-addon"]["win_exec_path"]
    是否存在；不查 PATH。这里允许通过 ODAFC_PATH 环境变量配置可执行文件位置。
    """
    oda_path = os.environ.get("ODAFC_PATH", "").strip().strip('"')
    if not oda_path:
        return
    if Path(oda_path).is_file():
        # 注意 ezdxf 选项键名 win_exec_path，值需为字符串
        ezdxf.options.set("odafc-addon", "win_exec_path", oda_path)


def _resolve_odafc_executable() -> str | None:
    """解析 ODA File Converter 可执行文件路径。

    优先级：
    1. 环境变量 ODAFC_PATH
    2. ezdxf 选项 odafc-addon.win_exec_path（Windows）/ unix_exec_path（Linux/macOS）
    3. PATH 中的 ODAFileConverter / ODAFileConverter.exe

    Returns:
        可执行文件路径字符串；未找到返回 None
    """
    # 1. ODAFC_PATH 环境变量
    oda_path = os.environ.get("ODAFC_PATH", "").strip().strip('"')
    if oda_path and Path(oda_path).is_file():
        return oda_path

    # 2. ezdxf 选项
    try:
        if os.name == "nt":
            path = ezdxf.options.get("odafc-addon", "win_exec_path")
        else:
            path = ezdxf.options.get("odafc-addon", "unix_exec_path")
        if path and Path(path).is_file():
            return str(path)
    except Exception:  # noqa: BLE001
        pass

    # 3. PATH 查找
    import shutil

    exe_name = "ODAFileConverter.exe" if os.name == "nt" else "ODAFileConverter"
    return shutil.which(exe_name)


def detect_odafc_version() -> str | None:
    """探测 ODA File Converter 版本号。

    实现方式：执行 `<oda_exe> --version` 或在 Windows 上读取 exe 文件版本信息。
    ODA FC 不一定支持 --version 标志，失败时尝试读取文件属性（Windows）
    或返回 None（无法探测）。

    结果缓存到模块级变量，避免重复 subprocess 调用。

    Returns:
        版本字符串（如 "27.1"）；无法探测返回 None
    """
    global _odafc_version_cache, _odafc_version_checked
    if _odafc_version_checked:
        return _odafc_version_cache
    _odafc_version_checked = True

    exe_path = _resolve_odafc_executable()
    if not exe_path:
        return None

    # 方式 1：尝试 --version 命令行（部分版本支持）
    try:
        result = subprocess.run(
            [exe_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        output = (result.stdout or "") + (result.stderr or "")
        # 匹配 "ODA File Converter 27.1" / "Version 27.1" / "27.1.0.0" 等
        match = re.search(r"(\d+\.\d+(?:\.\d+)*)", output)
        if match:
            _odafc_version_cache = match.group(1)
            return _odafc_version_cache
    except Exception:  # noqa: BLE001
        pass

    # 方式 2：Windows 上读取 exe 文件版本信息（通过 PowerShell）
    if os.name == "nt":
        try:
            ps_cmd = (
                f"(Get-Item '{exe_path}').VersionInfo.ProductVersion"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                shell=False,
            )
            output = (result.stdout or "").strip()
            if output and output != "0.0.0.0":
                # 形如 "27.1.0.0" → 取 "27.1"
                match = re.match(r"(\d+\.\d+)", output)
                if match:
                    _odafc_version_cache = match.group(1)
                    return _odafc_version_cache
        except Exception:  # noqa: BLE001
            pass

    # 方式 3：从可执行文件路径推断（Windows 默认安装路径含版本号）
    # C:\Program Files\ODA\ODAFileConverter 27.1\ODAFileConverter.exe
    try:
        path_str = str(exe_path)
        match = re.search(r"ODAFileConverter[\s_]*?(\d+\.\d+)", path_str)
        if match:
            _odafc_version_cache = match.group(1)
            return _odafc_version_cache
    except Exception:  # noqa: BLE001
        pass

    return None


def is_odafc_available() -> bool:
    """检测 ODA File Converter 是否可用，并对低版本给出升级提示。

    实现：调用 ezdxf.addons.odafc.is_installed()。在未安装时不抛异常，
    仅返回 False，并打印安装指引。
    已安装但版本低于 25.x 时打印升级提示（不阻断转换，仅警告）。

    Returns:
        True 表示 ODA File Converter 已安装且可执行
    """
    _ensure_odafc_path()
    try:
        installed = bool(odafc.is_installed())
    except Exception:  # noqa: BLE001
        installed = False
    if not installed:
        # 不使用 logging 以避免本模块对 app.logging 的循环依赖
        print(
            f"[odafc] ODA File Converter 未安装。安装指引：\n"
            f"  1. 注册并下载：{_ODA_INSTALL_URL}\n"
            f"  2. 推荐 27.1（2026 版，~27MB，AppImage 自带 Qt6 运行时）\n"
            f"  3. Windows 安装后默认路径："
            f" C:\\Program Files\\ODA\\ODAFileConverter\\ODAFileConverter.exe\n"
            f"  4. 设置环境变量 ODAFC_PATH 指向 ODAFileConverter.exe，"
            f"或将其目录加入 PATH\n"
            f"  5. 文档：{_ODA_DOC_URL}\n"
        )
        return installed

    # 已安装：版本探测（不阻断转换，仅警告）
    version = detect_odafc_version()
    if version is None:
        # 无法探测版本，不警告
        return True

    v_cur = _parse_version_tuple(version)
    v_min = _parse_version_tuple(_ODA_MIN_VERSION)
    v_rec = _parse_version_tuple(_ODA_RECOMMENDED_VERSION)

    if v_cur < v_min:
        print(
            f"[odafc] 警告：ODA File Converter 版本过低（{version} < {_ODA_MIN_VERSION}）。"
            f" 旧版本在 Linux 上需手动安装 Qt5/Qt6 运行时，且不兼容 DWG 2026。\n"
            f"  强烈建议升级到 {_ODA_RECOMMENDED_VERSION}：{_ODA_INSTALL_URL}\n"
        )
    elif v_cur < v_rec:
        # 低于推荐版本但 ≥ 最低版本，仅 debug 提示
        print(
            f"[odafc] 提示：ODA File Converter 版本 {version}，"
            f"推荐升级到 {_ODA_RECOMMENDED_VERSION} 以获得 DWG 2026 兼容性与 Qt6 集成。"
        )

    return True


def dwg_to_dxf(
    dwg_path: Path,
    output_dir: Path | None = None,
    version: str = "R2018",
) -> Path:
    """将 DWG 文件转换为 DXF 文件。

    Args:
        dwg_path: 输入 DWG 文件路径
        output_dir: 输出目录；默认与 dwg_path 同目录
        version: 输出 DXF 版本，如 "R2018" / "R2010" / "R12" 等
            （对应 ODA 的 ACAD2018 / ACAD2010 / ACAD12 等）

    Returns:
        生成的 DXF 文件路径

    Raises:
        ODANotAvailableError: ODA File Converter 未安装
        FileNotFoundError: 输入文件不存在
        odafc.UnsupportedVersion: 版本号非法
        odafc.UnknownODAFCError: 转换失败
    """
    if not is_odafc_available():
        raise ODANotAvailableError(
            "ODA File Converter 不可用，无法进行 DWG→DXF 转换。"
            f" 安装指引：{_ODA_INSTALL_URL}"
        )

    src = Path(dwg_path).absolute()
    if not src.is_file():
        raise FileNotFoundError(f"DWG 文件不存在: {src}")
    if src.suffix.lower() != ".dwg":
        raise ValueError(f"输入文件后缀非 .dwg: {src}")

    if output_dir is None:
        dest_dir = src.parent
    else:
        dest_dir = Path(output_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

    dest_path = dest_dir / src.with_suffix(".dxf").name

    # odafc.convert 签名：
    #   convert(source, dest="", *, version="R2018", audit=True, replace=False)
    # version 接受 "R2018" / "ACAD2018" / "AC1032" 等
    odafc.convert(
        str(src),
        str(dest_path),
        version=version,
        audit=True,
        replace=True,
    )

    if not dest_path.is_file():
        raise ODANotAvailableError(
            f"ODA 转换未生成预期文件: {dest_path}（可能 ODA 进程异常退出）"
        )
    return dest_path
