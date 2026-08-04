"""CAD 解析底座（Task 2）。

对外公共接口聚合：调用方优先从此包导入，避免直接依赖具体子模块。
所有外部引擎（OCP / FreeCAD / ODA File Converter）的 import 都在各自
子模块内 try/except 优雅降级，本包 import 安全。

支持格式：
- DXF：ezdxf 直接解析（SubTask 2.1）
- DWG：经 ODA File Converter 转 DXF 后解析（SubTask 2.2）
- STEP/IGES：OCP/pythonOCC B-Rep 几何查询（SubTask 2.3）
- 跨格式转换与几何校验：FreeCAD 备用引擎（SubTask 2.4）

统一中间表示：app.schemas.cad_intermediate.CADIntermediateModel（SubTask 2.5）
"""

from app.services.cad.dwg_converter import (
    ODANotAvailableError,
    dwg_to_dxf,
    is_odafc_available,
)
from app.services.cad.dxf_parser import (
    CADParseError,
    parse_dxf_to_intermediate,
)
from app.services.cad.freecad_engine import (
    FreeCADNotAvailableError,
    convert_format,
    is_freecad_available,
    validate_geometry,
)
from app.services.cad.occ_engine import (
    OCCEngineNotAvailableError,
    check_interference,
    get_bounding_box,
    get_surface_area,
    get_volume,
    is_occ_available,
    read_iges_file,
    read_step_file,
)

__all__ = [
    # DXF
    "CADParseError",
    "parse_dxf_to_intermediate",
    # DWG
    "ODANotAvailableError",
    "is_odafc_available",
    "dwg_to_dxf",
    # OCC
    "OCCEngineNotAvailableError",
    "is_occ_available",
    "read_step_file",
    "read_iges_file",
    "get_bounding_box",
    "get_volume",
    "get_surface_area",
    "check_interference",
    # FreeCAD
    "FreeCADNotAvailableError",
    "is_freecad_available",
    "convert_format",
    "validate_geometry",
]
