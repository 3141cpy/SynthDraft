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

不可用时调用方应捕获 ODANotAvailableError 或先调用 is_odafc_available()。
"""

from __future__ import annotations

import os
from pathlib import Path

import ezdxf
from ezdxf.addons import odafc

__all__ = ["ODANotAvailableError", "dwg_to_dxf", "is_odafc_available"]


_ODA_INSTALL_URL = "https://www.opendesign.com/guestfiles/oda_file_converter"
_ODA_DOC_URL = "https://ezdxf.readthedocs.io/en/stable/addons/odafc.html"


class ODANotAvailableError(RuntimeError):
    """ODA File Converter 未安装或不在 PATH / ODAFC_PATH 中。"""


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


def is_odafc_available() -> bool:
    """检测 ODA File Converter 是否可用。

    实现：调用 ezdxf.addons.odafc.is_installed()。在未安装时不抛异常，
    仅返回 False，并打印安装指引（仅首次或调试场景）。

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
            f"  2. Windows 安装后默认路径："
            f" C:\\Program Files\\ODA\\ODAFileConverter\\ODAFileConverter.exe\n"
            f"  3. 设置环境变量 ODAFC_PATH 指向 ODAFileConverter.exe，"
            f"或将其目录加入 PATH\n"
            f"  4. 文档：{_ODA_DOC_URL}\n"
        )
    return installed


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
