"""pythonOCC / OCP B-Rep 几何查询（SubTask 2.3）。

依赖：
- 优先：cadquery-ocp（PyPI 包名 cadquery-ocp，模块名 OCP），CadQuery 维护
  官方仓库：https://github.com/CadQuery/OCP
  PyPI：https://pypi.org/project/cadquery-ocp/
  Windows cp313 wheel 可用（截至 2026-07-25 最新 7.9.3.1.1）
- 备选：pythonocc-core（conda-forge 安装，模块名 OCC）
  官方仓库：https://github.com/tpaviot/pythonocc-core
  安装：conda install -c conda-forge pythonocc-core=7.8.1.1

OCP 与 pythonocc-core 的 API 命名约定不同：
- OCP：`from OCP.BRepBndLib import BRepBndLib; BRepBndLib.Add_s(shape, bbox, ...)`
        静态方法后缀 `_s`，模块/类同名（PascalCase）
- pythonocc-core：`from OCC.BRepBndLib import brepbndlib_Add; brepbndlib_Add(shape, bbox)`
        函数式命名（snake_case_CamelCase）

本模块优先用 OCP，缺失时回退 OCC，两者都不可用时 is_occ_available() 返回 False，
所有几何查询函数抛出 OCCEngineNotAvailableError。

官方文档：
- OCP：https://github.com/CadQuery/OCP（无独立文档，参考 OCCT 官方文档）
- OCCT：https://dev.opencascade.org/doc/occt-7.8.0/overview/html/index.html
- STEPControl_Reader：OCCT STEP 数据交换模块
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = [
    "OCCEngineNotAvailableError",
    "OCCTRenderError",
    "check_interference",
    "get_bounding_box",
    "get_surface_area",
    "get_volume",
    "is_occ_available",
    "read_step_file",
    "read_iges_file",
    "render_to_png",
]


# ===== 优雅降级：尝试导入 OCP 或 OCC =====
# 优先级：OCP（cadquery-ocp）> OCC（pythonocc-core）
_OCP_BACKEND: str | None = None

# 运行时按需查找的符号（延迟到首次调用时绑定）
_OCC_NAMESPACE: dict[str, Any] = {}

try:
    # —— OCP 路径 ——
    from OCP.IFSelect import IFSelect_RetDone  # type: ignore[import-not-found]
    from OCP.STEPControl import STEPControl_Reader  # type: ignore[import-not-found]
    from OCP.Bnd import Bnd_Box  # type: ignore[import-not-found]
    from OCP.BRepBndLib import BRepBndLib as _OCP_BRepBndLib  # type: ignore[import-not-found]
    from OCP.BRepGProp import BRepGProp as _OCP_BRepGProp  # type: ignore[import-not-found]
    from OCP.GProp import GProp_GProps  # type: ignore[import-not-found]
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common  # type: ignore[import-not-found]
    from OCP.TopoDS import TopoDS_Shape  # type: ignore[import-not-found]  # noqa: F401

    def _ocp_add_to_bbox(shape: Any, bbox: Any, use_triangulation: bool, use_tol: bool) -> None:
        """兼容不同 OCP 版本的 BRepBndLib.Add_s 调用。

        新版 OCP（如 7.9.x）：Add_s(S, B, useTriangulation=True) — 仅 3 参数
        旧版 OCP：Add_s(S, B, useTriangulation, useShapeTolerance) — 4 参数
        """
        try:
            _OCP_BRepBndLib.Add_s(shape, bbox, use_triangulation, use_tol)
        except TypeError:
            # 新版 OCP 不接受 useShapeTolerance 参数，降级为 3 参数
            _OCP_BRepBndLib.Add_s(shape, bbox, use_triangulation)

    _OCC_NAMESPACE.update({
        "IFSelect_RetDone": IFSelect_RetDone,
        "STEPControl_Reader": STEPControl_Reader,
        "Bnd_Box": Bnd_Box,
        "add_to_bounding_box": _ocp_add_to_bbox,
        "linear_properties": _OCP_BRepGProp.LinearProperties_s,
        "surface_properties": _OCP_BRepGProp.SurfaceProperties_s,
        "volume_properties": _OCP_BRepGProp.VolumeProperties_s,
        "GProp_GProps": GProp_GProps,
        "BRepAlgoAPI_Common": BRepAlgoAPI_Common,
        "bbox_get": lambda bbox: bbox.Get(),  # OCP: Bnd_Box.Get() -> tuple of 6 floats
        "is_null_shape": lambda s: bool(s.IsNull()),
        "iges_reader_module": "OCP.IGESControl",
    })
    _OCP_BACKEND = "OCP"
except ImportError:
    try:
        # —— pythonocc-core 路径 ——
        from OCC.IFSelect import IFSelect_RetDone  # type: ignore[import-not-found]
        from OCC.STEPControl import STEPControl_Reader  # type: ignore[import-not-found]
        from OCC.Bnd import Bnd_Box  # type: ignore[import-not-found]
        from OCC.BRepBndLib import brepbndlib_Add  # type: ignore[import-not-found]
        from OCC.BRepGProp import (  # type: ignore[import-not-found]
            brepgprop_LinearProperties as _occ_linear,
            brepgprop_SurfaceProperties as _occ_surface,
            brepgprop_VolumeProperties as _occ_volume,
        )
        from OCC.GProp import GProp_GProps  # type: ignore[import-not-found]
        from OCC.BRepAlgoAPI import BRepAlgoAPI_Common  # type: ignore[import-not-found]
        from OCC.TopoDS import TopoDS_Shape  # type: ignore[import-not-found]  # noqa: F401

        def _occ_add_to_bbox(shape: Any, bbox: Any, use_triangulation: bool, use_tol: bool) -> None:
            # pythonocc-core 的 brepbndlib_Add 签名： (shape, bbox[, useTriangulation])
            brepbndlib_Add(shape, bbox, use_triangulation)

        _OCC_NAMESPACE.update({
            "IFSelect_RetDone": IFSelect_RetDone,
            "STEPControl_Reader": STEPControl_Reader,
            "Bnd_Box": Bnd_Box,
            "add_to_bounding_box": _occ_add_to_bbox,
            "linear_properties": _occ_linear,
            "surface_properties": _occ_surface,
            "volume_properties": _occ_volume,
            "GProp_GProps": GProp_GProps,
            "BRepAlgoAPI_Common": BRepAlgoAPI_Common,
            "bbox_get": lambda bbox: bbox.Get(),
            "is_null_shape": lambda s: bool(s.IsNull()),
            "iges_reader_module": "OCC.IGESControl",
        })
        _OCP_BACKEND = "OCC"
    except ImportError:
        _OCP_BACKEND = None


_INSTALL_HINT = (
    "OCC 引擎不可用。安装方式（任选其一）：\n"
    "  方式 A（推荐，pip）：pip install cadquery-ocp==7.9.3.1.1  (Windows cp313 wheel 可用)\n"
    "  方式 B（conda）：conda install -c conda-forge pythonocc-core=7.8.1.1\n"
    "  官方文档：\n"
    "    - OCP: https://github.com/CadQuery/OCP\n"
    "    - pythonocc-core: https://github.com/tpaviot/pythonocc-core\n"
)


class OCCEngineNotAvailableError(RuntimeError):
    """OCC（OCP / pythonocc-core）未安装或不可用。"""


class OCCTRenderError(Exception):
    """OCCT 离屏渲染失败。"""
    pass


def is_occ_available() -> bool:
    """检测 OCP / pythonocc-core 是否可用。

    Returns:
        True 表示已成功导入 OCP 或 OCC 模块
    """
    return _OCP_BACKEND is not None


def _require_occ() -> None:
    """内部断言：OCC 可用，否则抛 OCCEngineNotAvailableError。"""
    if _OCP_BACKEND is None:
        raise OCCEngineNotAvailableError(_INSTALL_HINT)


def read_step_file(step_path: Path) -> dict:
    """读取 STEP 文件，返回顶层形状句柄与基本信息。

    Args:
        step_path: STEP 文件路径

    Returns:
        dict 包含：
        - shape: TopoDS_Shape 顶层形状
        - backend: "OCP" / "OCC"
        - nb_shapes: 顶层形状数（通常 1）
        - file: 文件路径

    Raises:
        OCCEngineNotAvailableError: OCC 未安装
        FileNotFoundError: 文件不存在
        RuntimeError: STEP 读取失败
    """
    _require_occ()
    path = Path(step_path)
    if not path.is_file():
        raise FileNotFoundError(f"STEP 文件不存在: {path}")

    reader = _OCC_NAMESPACE["STEPControl_Reader"]()
    status = reader.ReadFile(str(path))
    if status != _OCC_NAMESPACE["IFSelect_RetDone"]:
        raise RuntimeError(f"STEP 文件读取失败（status={status}）: {path}")

    reader.TransferRoots()
    nb = reader.NbShapes()
    shape = reader.OneShape()

    return {
        "shape": shape,
        "backend": _OCP_BACKEND,
        "nb_shapes": int(nb),
        "file": str(path),
    }


def read_iges_file(iges_path: Path) -> dict:
    """读取 IGES 文件，返回顶层形状句柄与基本信息。

    与 read_step_file 类似，使用 IGESControl_Reader。
    """
    _require_occ()
    path = Path(iges_path)
    if not path.is_file():
        raise FileNotFoundError(f"IGES 文件不存在: {path}")

    # 延迟导入：仅在 IGES 实际被使用时
    module_name = _OCC_NAMESPACE["iges_reader_module"]
    if _OCP_BACKEND == "OCP":
        from OCP.IGESControl import IGESControl_Reader  # type: ignore[import-not-found]
    else:
        from OCC.IGESControl import IGESControl_Reader  # type: ignore[import-not-found]

    reader = IGESControl_Reader()
    status = reader.ReadFile(str(path))
    if status != _OCC_NAMESPACE["IFSelect_RetDone"]:
        raise RuntimeError(f"IGES 文件读取失败（status={status}）: {path}")

    reader.TransferRoots()
    nb = reader.NbShapes()
    shape = reader.OneShape()

    return {
        "shape": shape,
        "backend": _OCP_BACKEND,
        "nb_shapes": int(nb),
        "file": str(path),
    }


def get_bounding_box(shape: Any) -> tuple[float, float, float, float, float, float]:
    """计算形状的轴对齐包围盒。

    Args:
        shape: TopoDS_Shape（来自 read_step_file()["shape"]）

    Returns:
        (xmin, ymin, zmin, xmax, ymax, zmax)

    Raises:
        OCCEngineNotAvailableError: OCC 未安装
    """
    _require_occ()
    bbox = _OCC_NAMESPACE["Bnd_Box"]()
    # use_triangulation=True, use_shape_tolerance=False（OCCT 7.x 默认推荐）
    _OCC_NAMESPACE["add_to_bounding_box"](shape, bbox, True, False)
    xmin, ymin, zmin, xmax, ymax, zmax = _OCC_NAMESPACE["bbox_get"](bbox)
    return (
        float(xmin), float(ymin), float(zmin),
        float(xmax), float(ymax), float(zmax),
    )


def get_volume(shape: Any) -> float:
    """计算形状体积（仅对实体/壳有意义）。

    Args:
        shape: TopoDS_Shape

    Returns:
        体积（立方单位，与文件单位一致；STEP 默认 mm）

    Raises:
        OCCEngineNotAvailableError: OCC 未安装
    """
    _require_occ()
    props = _OCC_NAMESPACE["GProp_GProps"]()
    _OCC_NAMESPACE["volume_properties"](shape, props)
    return float(props.Mass())


def get_surface_area(shape: Any) -> float:
    """计算形状表面积。

    Args:
        shape: TopoDS_Shape

    Returns:
        表面积（平方单位）

    Raises:
        OCCEngineNotAvailableError: OCC 未安装
    """
    _require_occ()
    props = _OCC_NAMESPACE["GProp_GProps"]()
    _OCC_NAMESPACE["surface_properties"](shape, props)
    return float(props.Mass())


def check_interference(shape_a: Any, shape_b: Any) -> bool:
    """检测两个形状是否干涉（共享体积）。

    使用 BRepAlgoAPI_Common 布尔相交运算；若相交结果非空则视为干涉。

    Args:
        shape_a, shape_b: TopoDS_Shape

    Returns:
        True 表示两形状存在几何干涉

    Raises:
        OCCEngineNotAvailableError: OCC 未安装
    """
    _require_occ()
    common = _OCC_NAMESPACE["BRepAlgoAPI_Common"](shape_a, shape_b)
    common.Build()
    result_shape = common.Shape()
    # 空形状判定：通过 TopoDS_Shape.IsNull()
    try:
        if _OCC_NAMESPACE["is_null_shape"](result_shape):
            return False
    except Exception:  # noqa: BLE001
        pass
    # 进一步：相交结果体积 > 0 才视为干涉（避免仅共面/共边误报）
    try:
        vol = get_volume(result_shape)
    except Exception:  # noqa: BLE001
        return True  # 无法计算体积时，保守视为干涉
    return vol > 0.0


def render_to_png(
    shape: Any,
    output_path: str | Path,
    view: str = "iso",
    width: int = 1024,
    height: int = 768,
) -> str:
    """将 OCC shape 离屏渲染为 PNG。

    使用 OCCT V3d_View.ToPixMap 离屏渲染（无需 GUI/显示器），适用于 headless 环境。
    OCP（cadquery-ocp）不含 SimpleGui 模块，因此直接基于 V3d/OpenGl/AIS 原生 API
    构建离屏渲染管线：GraphicDriver → V3d_Viewer → V3d_View → 虚拟 NeutralWindow
    → AIS_InteractiveContext.Display(AIS_Shape) → ToPixMap → 逐像素提取保存 PNG。

    Args:
        shape: OCC TopoDS_Shape 对象
        output_path: 输出 PNG 路径
        view: 视角，"iso"（等轴侧）/ "front" / "top"
        width: 图片宽度
        height: 图片高度

    Returns:
        输出 PNG 路径

    Raises:
        OCCTRenderError: 离屏渲染失败（如 OpenGL 上下文创建失败、shape 无效）
    """
    _require_occ()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 延迟导入渲染模块，避免模块加载时强依赖
    try:
        if _OCP_BACKEND == "OCP":
            from OCP.OpenGl import OpenGl_GraphicDriver
            from OCP.Aspect import Aspect_DisplayConnection, Aspect_NeutralWindow
            from OCP.Image import Image_PixMap, Image_Format_RGB
            from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
            from OCP.AIS import AIS_InteractiveContext, AIS_Shaded, AIS_Shape
            from OCP.V3d import V3d_Viewer, V3d_View, V3d_TypeOfOrientation
            from OCP.BRepMesh import BRepMesh_IncrementalMesh
        elif _OCP_BACKEND == "OCC":
            from OCC.Core.OpenGl import OpenGl_GraphicDriver
            from OCC.Core.Aspect import Aspect_DisplayConnection, Aspect_NeutralWindow
            from OCC.Core.Image import Image_PixMap, Image_Format_RGB
            from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
            from OCC.Core.AIS import AIS_InteractiveContext, AIS_Shaded, AIS_Shape
            from OCC.Core.V3d import V3d_Viewer, V3d_View, V3d_TypeOfOrientation
            from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
        else:
            raise OCCTRenderError("OCC 引擎不可用，无法渲染")
    except ImportError as e:
        raise OCCTRenderError(f"OCC 渲染模块不可用: {e}") from e

    # 视角映射
    view_map = {
        "iso": V3d_TypeOfOrientation.V3d_XposYnegZpos,
        "front": V3d_TypeOfOrientation.V3d_Yneg,
        "top": V3d_TypeOfOrientation.V3d_Zpos,
    }
    proj = view_map.get(view, view_map["iso"])

    try:
        # 1. 图形驱动 + 虚拟显示连接（headless 关键）
        display_conn = Aspect_DisplayConnection()
        driver = OpenGl_GraphicDriver(display_conn)
        driver.ChangeOptions().swapInterval = 0

        # 2. Viewer + View
        viewer = V3d_Viewer(driver)
        viewer.SetDefaultViewSize(1000.0)
        viewer.SetDefaultBackgroundColor(Quantity_Color(1.0, 1.0, 1.0, Quantity_TOC_RGB))

        view_obj = V3d_View(viewer)
        view_obj.SetImmediateUpdate(False)

        # 3. 虚拟窗口（headless 离屏渲染关键：SetVirtual(True)）
        window = Aspect_NeutralWindow()
        window.SetVirtual(True)
        window.SetSize(width, height)
        view_obj.SetWindow(window)

        # 4. 交互上下文 + 网格化 + Display
        context = AIS_InteractiveContext(viewer)
        BRepMesh_IncrementalMesh(shape, 0.1).Perform()
        ais_obj = AIS_Shape(shape)
        context.Display(ais_obj, int(AIS_Shaded), -1, True)
        context.SetDisplayMode(int(AIS_Shaded), True)

        # 5. 视角 + FitAll
        view_obj.SetProj(proj)
        view_obj.FitAll()
        view_obj.ZFitAll()
        view_obj.Redraw()

        # 6. 离屏渲染到 pixmap
        pixmap = Image_PixMap()
        pixmap.SetFormat(Image_Format_RGB)
        if not view_obj.ToPixMap(pixmap, width, height):
            raise OCCTRenderError("V3d_View.ToPixMap 返回 False")

        # 7. 提取像素数据保存 PNG
        # OCP 的 Data()/Row() 返回指针 int 但绑定有缺陷（返回首字节值），
        # 改用 PixelColor 逐像素读取（慢但可靠）。PixelColor 返回 Quantity_ColorRGBA。
        import numpy as np
        from PIL import Image

        sx = pixmap.SizeX()
        sy = pixmap.SizeY()
        arr = np.zeros((sy, sx, 3), dtype=np.uint8)
        for y in range(sy):
            for x in range(sx):
                rgba = pixmap.PixelColor(x, y)
                rgb = rgba.GetRGB()
                arr[y, x, 0] = int(rgb.Red() * 255)
                arr[y, x, 1] = int(rgb.Green() * 255)
                arr[y, x, 2] = int(rgb.Blue() * 255)
        # OCCT pixmap 默认 topDown=False（bottom-up），PIL 需要翻转
        if not pixmap.IsTopDown():
            arr = arr[::-1]

        Image.fromarray(arr, "RGB").save(str(output_path))
        return str(output_path)
    except OCCTRenderError:
        raise
    except Exception as e:
        raise OCCTRenderError(f"OCCT 离屏渲染失败: {e}") from e
