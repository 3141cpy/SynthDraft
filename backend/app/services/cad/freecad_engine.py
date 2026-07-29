"""FreeCAD 备用引擎（SubTask 2.4）。

FreeCAD 作为 Python 模块在 Windows 上需手动配置 PYTHONPATH：
- 安装 FreeCAD（https://www.freecadweb.org/downloads.php）
- 将 FreeCAD 安装目录（含 FreeCAD.pyd / FreeCADCmd.pyd / bin、lib、Mod、Ext 等子目录）
  加入 PYTHONPATH，或将 bin 加入 PATH
- 验证：python -c "import FreeCAD; print(FreeCAD.Version())"

本模块所有函数在 FreeCAD 未安装时优雅降级：抛 FreeCADNotAvailableError，
is_freecad_available() 返回 False。

支持的格式转换：
- 输入：STEP / IGES / BRep / STL / OBJ / DWG（经 ODA）/ DXF
- 输出：STEP / IGES / BRep / STL / OBJ / DXF / VRML

注意：DWG 经 FreeCAD 转换需要安装 ODA 转换插件（FreeCAD 内置 ODA Converter）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = [
    "FreeCADNotAvailableError",
    "convert_format",
    "is_freecad_available",
    "validate_geometry",
]


# ===== 优雅降级：尝试导入 FreeCAD =====
_FreeCAD: Any = None
_Part: Any = None
_FREECAD_AVAILABLE: bool = False

try:
    import FreeCAD as _FreeCAD  # type: ignore[import-not-found]
    import Part as _Part  # type: ignore[import-not-found]
    _FREECAD_AVAILABLE = True
except ImportError:
    _FREECAD_AVAILABLE = False


_INSTALL_HINT = (
    "FreeCAD 不可用。安装与配置：\n"
    "  1. 下载安装：https://www.freecadweb.org/downloads.php\n"
    "  2. Windows：将 FreeCAD 安装目录（含 FreeCAD.pyd）加入 PYTHONPATH，\n"
    "     或将 bin 目录加入 PATH 后重启 Python 进程\n"
    "  3. 验证：python -c \"import FreeCAD; print(FreeCAD.Version())\"\n"
    "  4. 文档：https://wiki.freecadweb.org/Embedding_FreeCAD\n"
)


class FreeCADNotAvailableError(RuntimeError):
    """FreeCAD 未安装或不可作为 Python 模块导入。"""


def is_freecad_available() -> bool:
    """检测 FreeCAD 是否可作为 Python 模块导入。

    Returns:
        True 表示 import FreeCAD 与 import Part 成功
    """
    return _FREECAD_AVAILABLE


def _require_freecad() -> None:
    """内部断言：FreeCAD 可用，否则抛 FreeCADNotAvailableError。"""
    if not _FREECAD_AVAILABLE:
        raise FreeCADNotAvailableError(_INSTALL_HINT)


# 支持的输入/输出格式后缀（小写，无点）
_SUPPORTED_INPUT_FORMATS = {"step", "stp", "iges", "igs", "brep", "stl", "obj", "dxf"}
_SUPPORTED_OUTPUT_FORMATS = {"step", "stp", "iges", "igs", "brep", "stl", "obj", "dxf", "vrml"}


def convert_format(input_path: Path, output_format: str) -> Path:
    """跨格式转换。

    使用 FreeCAD Part.read 加载输入形状，再用 shape.exportXxx 写出为目标格式。

    Args:
        input_path: 输入文件路径（STEP/IGES/BRep/STL/OBJ/DXF）
        output_format: 目标格式后缀（不含点），如 "step" / "iges" / "stl" 等

    Returns:
        输出文件路径（与输入同目录，仅后缀不同）

    Raises:
        FreeCADNotAvailableError: FreeCAD 不可用
        FileNotFoundError: 输入文件不存在
        ValueError: 输入/输出格式不支持
        RuntimeError: 转换失败
    """
    _require_freecad()

    src = Path(input_path)
    if not src.is_file():
        raise FileNotFoundError(f"输入文件不存在: {src}")
    in_ext = src.suffix.lower().lstrip(".")
    if in_ext not in _SUPPORTED_INPUT_FORMATS:
        raise ValueError(f"不支持的输入格式: {in_ext}")

    out_fmt = output_format.lower().lstrip(".")
    if out_fmt not in _SUPPORTED_OUTPUT_FORMATS:
        raise ValueError(f"不支持的输出格式: {out_fmt}")

    dest = src.with_suffix(f".{out_fmt}")

    # Part.read 支持根据后缀自动选择 reader
    shape = _Part.read(str(src))
    if shape is None:
        raise RuntimeError(f"FreeCAD 读取失败: {src}")

    # 不同格式的导出方法不同
    export_method_map = {
        "step": "exportStep",
        "stp": "exportStep",
        "iges": "exportIges",
        "igs": "exportIges",
        "brep": "exportBrep",
        "stl": "exportStl",
        "obj": "exportObj",
        "dxf": "exportDxf",
        "vrml": "exportVrml",
    }
    method_name = export_method_map[out_fmt]

    # DXF 特殊处理：FreeCAD Part 模块无 exportDxf，使用 Import 模块导出
    # Import.export 签名为 (shape_list, filename)
    if out_fmt == "dxf":
        try:
            import Import as _Import  # type: ignore[import-not-found]
        except ImportError:
            raise RuntimeError(
                "FreeCAD DXF 导出需要 Import 模块，但当前不可用"
            )
        _Import.export([shape], str(dest))
        if not dest.is_file():
            raise RuntimeError(f"FreeCAD DXF 导出失败：未生成文件 {dest}")
        return dest

    export_fn = getattr(_Part, method_name, None)
    if export_fn is None:
        raise RuntimeError(f"FreeCAD Part.{method_name} 不存在（输出格式 {out_fmt}）")
    # FreeCAD Part 模块级导出 API 签名为 exportStep(shape_list, filename)
    # 即先 shape_list 后 filename（原代码参数顺序写反）
    rc = export_fn([shape], str(dest))
    if not dest.is_file():
        raise RuntimeError(
            f"FreeCAD 导出失败（rc={rc}）：未生成文件 {dest}"
        )
    return dest


def validate_geometry(shape: Any) -> list[str]:
    """几何校验：返回问题列表。

    使用 FreeCAD Part.Shape 的 isValid / check 等方法检测：
    - 是否为空形状
    - 是否闭合
    - 是否自相交
    - 是否开放壳

    Args:
        shape: TopoDS_Shape 或 FreeCAD Part.Shape。
            若传入 dict（来自 occ_engine.read_step_file），自动取 shape 字段。

    Returns:
        问题字符串列表；空列表表示无问题。

    Raises:
        FreeCADNotAvailableError: FreeCAD 不可用
    """
    _require_freecad()

    # 兼容 occ_engine.read_step_file 返回的 dict
    if isinstance(shape, dict) and "shape" in shape:
        shape = shape["shape"]

    issues: list[str] = []

    # 若 shape 不是 FreeCAD Part.Shape（例如 OCP TopoDS_Shape），跨引擎直接转换
    # 需经 BREP 文件中转，超出本函数职责。调用方应自行调用 occ_engine 中的
    # 对应函数，或将 shape 导出为 BREP 后再读入 FreeCAD。
    if not hasattr(shape, "isValid"):
        return ["unknown_shape_type: 传入的 shape 无法被 FreeCAD 识别（请使用 BREP 文件中转）"]

    if not shape.isValid():
        issues.append("shape_not_valid: FreeCAD 判定形状无效")

    # 自相交检查（仅对壳/实体有意义）
    try:
        if hasattr(shape, "check"):
            # check() 返回字符串描述错误，空字符串表示无错
            err = shape.check()
            if err:
                issues.append(f"check_failed: {err}")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"check_exception: {type(exc).__name__}: {exc}")

    # 开放壳检测
    try:
        for shell in shape.Shells:
            if not shell.isClosed():
                issues.append("open_shell: 存在未闭合的壳")
                break
    except Exception:  # noqa: BLE001
        pass

    return issues
